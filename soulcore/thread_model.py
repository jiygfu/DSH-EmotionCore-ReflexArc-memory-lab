#!/usr/bin/env python3
"""Deterministic event-thread assignment.

A thread is a continuing real-world event, not a 20-minute chat block. Adjacent
episodes in the same conversation are joined only when they are close enough and
share content; old closed/archived threads are never reopened by this pass.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from typing import Any

from . import appraise, db

# Same-conversation chunks within this window are treated as one thread.
SAME_SESSION_HOURS = 1.5
# Beyond same-session: only merge with lexical overlap.
LOOSE_HOURS = 36
LOOSE_OVERLAP = 0.12
STRONG_HOURS = 72
STRONG_OVERLAP = 0.22
MAX_THREAD_ITEMS = 16
MAX_THREAD_HOURS = 48
THREAD_MIN_IMPORTANCE = 0.25
THREAD_MAX_UNRESOLVED = 0.30


def _parse(ts: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.astimezone()
        return d.astimezone()
    except Exception:
        return None


def _grams(text: str) -> set[str]:
    s = re.sub(r"[\s\W_]+", "", str(text or ""))
    if not s:
        return set()
    out = set()
    for i in range(max(0, len(s) - 1)):
        out.add(s[i:i + 2])
    return out


def _overlap(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / max(1, len(ga | gb))


def _participants(raw: Any) -> set[str]:
    try:
        data = json.loads(raw or "[]")
        return {str(x) for x in data if str(x).strip()}
    except Exception:
        return set()


def _text(ep: sqlite3.Row) -> str:
    return f"{ep['summary'] or ''} {ep['key_quote'] or ''} {ep['felt'] or ''}"


def _cache_get(conn, pair_key: str) -> tuple[bool, float, str] | None:
    try:
        row = conn.execute(
            "SELECT decision,confidence,reason FROM thread_merge_reviews WHERE pair_key=?",
            (pair_key,),
        ).fetchone()
        if not row:
            return None
        return bool(row["decision"]), float(row["confidence"] or 0), str(row["reason"] or "")
    except Exception:
        return None


def _cache_put(conn, pair_key: str, left: str, right: str, same: bool, confidence: float, reason: str, now: str) -> None:
    try:
        conn.execute(
            """INSERT OR REPLACE INTO thread_merge_reviews
               (pair_key,left_id,right_id,decision,confidence,reason,reviewed_at)
               VALUES (?,?,?,?,?,?,?)""",
            (pair_key, left, right, 1 if same else 0, confidence, reason[:300], now),
        )
    except Exception:
        pass


def _model_same(conn, prev, ep, *, gap_h: float, overlap: float, cfg: dict, now: str) -> tuple[bool, float, str]:
    pair_key = f"{prev['id']}|{ep['id']}"
    cached = _cache_get(conn, pair_key)
    if cached is not None:
        return cached
    prompt = f"""你是本地事件线程整理器，不是对话角色。
判断“当前片段”是否属于“前一片段”所在的同一件持续事件。

同一事件的信号：同一话题/同一请求/同一问题/同一计划/同一冲突，或当前片段明显是前一片段的后续。
新事件的信号：换了话题、只是同一个人闲聊、只是同一群里无关的插话、前一件事已经收尾。
不确定就 same_event=false，并降低 confidence。

只输出 JSON：
{{"same_event": true/false, "confidence": 0.0-1.0, "reason": "一句中文理由"}}

前一片段：
摘要：{str(prev['summary'] or '')[:500]}
引语：{str(prev['key_quote'] or '')[:260]}
感受：{str(prev['felt'] or '')[:180]}

当前片段：
摘要：{str(ep['summary'] or '')[:500]}
引语：{str(ep['key_quote'] or '')[:260]}
感受：{str(ep['felt'] or '')[:180]}

时间间隔约 {gap_h:.1f} 小时；文本词重叠约 {overlap:.2f}。
"""
    try:
        body = {
            "model": str(cfg.get("model") or db.MODEL),
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 150},
        }
        data = appraise._post_json(
            "/api/generate", body, timeout=120,
            base_url=str(cfg.get("base_url") or "http://127.0.0.1:11434"),
        )
        parsed = json.loads(appraise._strip_json(str(data.get("response") or "")))
        same = bool(parsed.get("same_event"))
        confidence = max(0.0, min(1.0, float(parsed.get("confidence") or 0.0)))
        reason = str(parsed.get("reason") or "")[:300]
    except Exception:
        same = overlap >= LOOSE_OVERLAP
        confidence = 0.35
        reason = "local model failed; lexical fallback"
    _cache_put(conn, pair_key, str(prev["id"]), str(ep["id"]), same, confidence, reason, now)
    return same, confidence, reason


def _archive_low_signal(conn, thread_id: str, items: list[sqlite3.Row], now: str) -> bool:
    if not thread_id or not items:
        return False
    max_i = max(float(x["importance"] or 0) for x in items)
    max_u = max(float(x["unresolved"] or 0) for x in items)
    if max_i >= THREAD_MIN_IMPORTANCE or max_u >= THREAD_MAX_UNRESOLVED:
        return False
    cur = conn.execute(
        "UPDATE episodes SET status='archived', resolution_note=COALESCE(resolution_note,'auto: low-signal thread'), updated_at=? WHERE thread_id=? AND status='open'",
        (now, thread_id),
    )
    return bool(cur.rowcount)


def assign_threads(conn: sqlite3.Connection, *, max_model_reviews: int = 8) -> dict[str, int]:
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS thread_merge_reviews (
              pair_key TEXT PRIMARY KEY,
              left_id TEXT NOT NULL,
              right_id TEXT NOT NULL,
              decision INTEGER NOT NULL,
              confidence REAL NOT NULL DEFAULT 0,
              reason TEXT,
              reviewed_at TEXT NOT NULL
            )"""
        )
    except Exception:
        pass
    rows = conn.execute(
        """SELECT * FROM episodes
           ORDER BY conversation_key ASC, COALESCE(start_at, created_at) ASC, id ASC"""
    ).fetchall()
    by_conv: dict[str, list[sqlite3.Row]] = {}
    for ep in rows:
        by_conv.setdefault(str(ep["conversation_key"] or ""), []).append(ep)

    cfg = appraise.appraiser_config()
    threads = 0
    merged = 0
    model_reviews = 0
    model_merges = 0
    archived = 0
    now = datetime.now().astimezone().isoformat()
    for conv, eps in by_conv.items():
        current: list[sqlite3.Row] = []
        current_tid = ""
        current_last: datetime | None = None
        for ep in eps:
            if str(ep["status"] or "open") in ("archived", "closed") and ep["thread_id"]:
                # Keep finalized threads stable; do not re-thread their old chunks.
                continue
            start = _parse(ep["start_at"])
            end = _parse(ep["end_at"]) or start
            prev = current[-1] if current else None
            prev_end = current_last
            merge = False
            if prev is not None and prev_end is not None and start is not None:
                gap_h = max(0.0, (start - prev_end).total_seconds() / 3600)
                same_people = bool(_participants(ep["participants_json"]) & _participants(prev["participants_json"]))
                ov = _overlap(_text(prev), _text(ep))
                if str(prev["status"] or "open") not in ("open", "waiting", "paused"):
                    merge = False
                else:
                    thread_hours = max(0.0, (start - (_parse(current[0]["start_at"]) or start)).total_seconds() / 3600) if current else 0.0
                    if len(current) >= MAX_THREAD_ITEMS or thread_hours > MAX_THREAD_HOURS:
                        merge = False
                    elif gap_h <= SAME_SESSION_HOURS and same_people and ov >= 0.02:
                        merge = True
                    elif gap_h > STRONG_HOURS or ov < 0.02:
                        merge = False
                    elif ov >= STRONG_OVERLAP:
                        merge = True
                    elif model_reviews < max(0, int(max_model_reviews)):
                        same, confidence, reason = _model_same(
                            conn, prev, ep, gap_h=gap_h, overlap=ov,
                            cfg=cfg, now=now,
                        )
                        model_reviews += 1
                        merge = bool(same and confidence >= 0.62)
                        if merge:
                            model_merges += 1
                    else:
                        merge = ov >= LOOSE_OVERLAP
            if not merge:
                if current:
                    archived += 1 if _archive_low_signal(conn, current_tid, current, now) else 0
                current_tid = "th_" + hashlib.sha1(
                    f"{conv}|{ep['id']}|{ep['start_at'] or ''}".encode("utf-8")
                ).hexdigest()[:16]
                current = []
                threads += 1
            else:
                merged += 1
            current.append(ep)
            current_last = end or start or current_last
            prev_id = current[-2]["id"] if len(current) > 1 else None
            conn.execute(
                """UPDATE episodes
                   SET thread_id=?, continues_episode_id=?, last_seen_at=?, updated_at=?
                   WHERE id=?""",
                (current_tid, prev_id, (current_last.isoformat() if current_last else now), now, ep["id"]),
            )
            try:
                ids = json.loads(ep["raw_ids_json"] or "[]")
            except Exception:
                ids = []
            for mid in ids:
                conn.execute("UPDATE memories SET thread_id=? WHERE id=?", (current_tid, str(mid)))
        if current:
            archived += 1 if _archive_low_signal(conn, current_tid, current, now) else 0
    conn.commit()
    return {
        "episodes": len(rows), "threads": threads, "merged": merged,
        "model_reviews": model_reviews, "model_merges": model_merges, "archived": archived,
    }
