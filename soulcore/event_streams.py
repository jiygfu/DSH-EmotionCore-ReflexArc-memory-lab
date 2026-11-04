#!/usr/bin/env python3
"""Read-only local matching for the session-chunk / event-stream design.

This module intentionally does not write to the database and does not call a
model. It is the Phase-2 shadow matcher: given today's chunks, find likely
existing open loops, with conservative rules and a small local token overlap.

The public unfinished marker remains ``thread_loops`` (and ``anchor_at``);
this module never creates a second scheduler.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from typing import Any

ROLEPLAY_RE = re.compile(r"(跑团|扮演|剧情|回合|检定|骰|dm|npc|夜场|旁白|你走进|门楣|金铃|角色卡|主持人)")
TECH_RE = re.compile(r"(模型|代码|api|配置|部署|上下文|数据库|接口|测试|报错|本地|系统|程序|token|记忆|检索|提示词)")
STAGE_RE = re.compile(r"[（(][^）)]{2,}[）)]")
COMMON_GRAMS = {
    "这个", "那个", "就是", "还是", "可以", "没有", "什么", "怎么", "现在",
    "然后", "因为", "所以", "但是", "不是", "我们", "你们", "他们", "自己",
    "一个", "一下", "已经", "觉得", "知道", "这样", "那样",
}


def _text_domain(text: str) -> dict[str, Any]:
    low = str(text or "").lower()
    rp_terms = set(ROLEPLAY_RE.findall(low))
    rp_score = len(rp_terms) + (1 if STAGE_RE.search(low) and len(rp_terms) >= 2 else 0)
    tech_score = len(set(TECH_RE.findall(low)))
    roleplay = rp_score >= 3 and tech_score < 3
    return {
        "domain": "roleplay" if roleplay else "real",
        "content_class": "roleplay_entertainment" if roleplay else "ordinary",
        "long_term_eligible": not roleplay,
        "personality_eligible": not roleplay,
        "confidence_tier": "low" if roleplay else "normal",
        "reference_weight": 0.60 if roleplay else 1.0,
        "emotion_boost": ["fun", "curiosity"] if roleplay else [],
    }


def _tokens(text: str) -> set[str]:
    s = str(text or "").lower()
    out: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", s):
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            if g not in COMMON_GRAMS:
                out.add(g)
    for w in re.findall(r"[a-z0-9_]{2,}", s):
        out.add(w)
    return out


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def load_loops(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Load existing open loops; thread_loops remains the canonical marker."""
    rows = conn.execute(
        """SELECT l.thread_id,l.status,l.kind,l.one_line,l.anchor_text,l.anchor_at,
                  e.day,e.start_at,e.end_at,e.conversation_key,e.participants_json,
                  e.summary,e.key_quote
           FROM thread_loops l
           JOIN episodes e ON e.thread_id=l.thread_id AND e.status='open'
           ORDER BY e.day, e.start_at"""
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(str(row["thread_id"]), []).append(row)
    loops: list[dict[str, Any]] = []
    for tid, items in groups.items():
        items = sorted(items, key=lambda r: (str(r["day"] or ""), str(r["start_at"] or "")))
        latest = items[-1]
        names: list[str] = []
        for row in items:
            try:
                for n in json.loads(row["participants_json"] or "[]"):
                    if str(n) and str(n) not in names:
                        names.append(str(n))
            except Exception:
                pass
        text = " ".join(
            [str(latest["one_line"] or ""), str(latest["summary"] or ""), str(latest["key_quote"] or "")]
        )
        dom = _text_domain(text)
        loops.append({
            "thread_id": tid,
            "status": str(latest["status"] or "open"),
            "kind": str(latest["kind"] or ""),
            "one_line": str(latest["one_line"] or latest["summary"] or ""),
            "anchor_text": str(latest["anchor_text"] or ""),
            "anchor_at": latest["anchor_at"],
            "last_day": max(str(x["day"] or "") for x in items),
            "first_day": min(str(x["day"] or "") for x in items),
            "conversation_key": str(latest["conversation_key"] or ""),
            "participants": names,
            "text": text,
            "tokens": _tokens(text),
            **dom,
            # Roleplay anchors are for in-fiction recall, never real reminders.
            "real_trigger_eligible": dom["domain"] == "real" and bool(latest["anchor_at"]),
        })
    return loops


def match_chunk(conn: sqlite3.Connection, chunk: dict[str, Any], loops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return top 3 conservative cross-day candidates for one chunk."""
    day = str(chunk.get("day") or "")
    ckey = str(chunk.get("conversation_key") or "")
    ctokens = _tokens(" ".join([str(chunk.get("summary") or ""), str(chunk.get("signals") or "")]))
    cpeople = {str(x) for x in (chunk.get("participants") or []) if str(x)}
    cdomain = str(chunk.get("domain") or "real")
    out: list[dict[str, Any]] = []
    for loop in loops:
        # Cross-day only; do not match a chunk to the same day's own loop.
        if str(loop.get("last_day") or "") >= day:
            continue
        if str(loop.get("domain") or "real") != cdomain:
            continue
        if ckey and loop.get("conversation_key") and ckey != loop.get("conversation_key"):
            continue
        sim = _overlap(ctokens, loop.get("tokens") or set())
        rare = sim
        lpeople = {str(x) for x in (loop.get("participants") or []) if str(x)}
        people = len(cpeople & lpeople) / max(1, min(len(cpeople), len(lpeople))) if cpeople and lpeople else 0.0
        try:
            age = max(0, (date.fromisoformat(day) - date.fromisoformat(str(loop.get("last_day") or day))).days)
        except Exception:
            age = 14
        recency = max(0.0, 1.0 - age / 14.0)
        unresolved = 0.10 if str(loop.get("status")) in ("waiting", "paused", "closing") else 0.0
        score = 0.40 * sim + 0.20 * rare + 0.15 * people + 0.15 * unresolved + 0.10 * recency
        if ckey and loop.get("conversation_key"):
            score += 0.02
        if score <= 0:
            continue
        out.append({
            "thread_id": loop["thread_id"],
            "score": round(min(1.0, score), 3),
            "text_overlap": round(sim, 3),
            "participant_overlap": round(people, 3),
            "age_days": age,
            "status": loop["status"],
            "domain": loop["domain"],
            "anchor_at": loop["anchor_at"],
            "real_trigger_eligible": loop["real_trigger_eligible"],
            "one_line": str(loop["one_line"])[:160],
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:3]


def classify_match(score: float) -> str:
    if score >= 0.72:
        return "auto_candidate"
    if score >= 0.50:
        return "gray_candidate"
    return "new_stream"
