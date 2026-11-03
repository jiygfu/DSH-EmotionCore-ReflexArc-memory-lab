#!/usr/bin/env python3
"""Online event review that runs during dream/sleep.

This is deliberately **not** the local 2B reviewer. Sleep already has a
deterministic lifecycle (`close_episodes`, `thread_loops`, consolidation);
this module adds an online second pass that can read associated memories and
mark an unfinished event as resolved/waiting/abandoned.

It never decides closure on its own: `appraise._openai_chat` provides a
proposal, then local guards (open question/request, confidence, current
signals) decide what is written.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from . import appraise, config, db, retrieval
from . import episode_review

DREAM_CONFIG_PATH = Path(os.environ.get("EMOTIONCORE_DREAM_CONFIG") or (db.ROOT / "data" / "dream-config.json"))

PROMPT = """你是这个角色的「睡眠事件整理器」，不是聊天角色。
你在睡前复盘一个可能还没结束的事件线程。请只输出 JSON，不要 Markdown。

只输出：
{{"state":"resolved|ongoing|waiting|abandoned","confidence":0.0-1.0,
  "chatter":true/false,
  "reason":"一句中文理由，必须引用材料里的证据"}}

判断规则：
- resolved：问题已答复、请求已完成、双方明确收尾；不能只因为“过了很久”就 resolved；
- waiting：仍有未答问题、未完成请求、约好的后续，或需要对方回应；
- ongoing：事件还在推进，但当前没有明确的未答问题；
- abandoned：明确不继续、取消、散场，且没有待兑现承诺；
- chatter：纯刷屏、复读、无信息量吹水、表情/短句互刷，且不包含关系/承诺/冲突；
- 不确定就用 ongoing/waiting，confidence 降低；不要编造材料里没有的信息。

事件日期：{day}
线程状态：{thread_status}
最后消息类型：{last_kind}
最后一条消息：{last_text}
有未答问题：{has_question}
有未完成请求：{has_request}
有明确道别：{has_ending}
有收束语气：{settled}

线程片段：
{segments}

检索到的相关旧记忆/联想（只作证据，不要当新事实）：
{associations}
"""


def dream_config() -> dict[str, Any]:
    """Online-only dream config; data/dream-config.json overrides defaults."""
    cfg = dict(getattr(config, "DREAM", {}))
    try:
        raw = json.loads(DREAM_CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update(raw)
    except Exception:
        pass
    for key, env in (
        ("provider", "SOULCORE_DREAM_PROVIDER"),
        ("model", "SOULCORE_DREAM_MODEL"),
        ("base_url", "SOULCORE_DREAM_BASE_URL"),
        ("api_key_env", "SOULCORE_DREAM_API_KEY_ENV"),
    ):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def _api_key(cfg: dict[str, Any]) -> str:
    key = appraise._api_key(cfg)
    if key:
        return key
    # Reuse the existing DSH credential seam; never print/log the key.
    try:
        from . import balance
        return balance._api_key()
    except Exception:
        return ""


def _online(cfg: dict[str, Any]) -> bool:
    return str(cfg.get("provider") or "").lower() in ("api", "openai")


def _segments(items: list[sqlite3.Row]) -> str:
    parts: list[str] = []
    for i, row in enumerate(items[:4], 1):
        parts.append(
            f"[片段{i}] {row['day'] or ''} unresolved={float(row['unresolved'] or 0):.2f}\n"
            f"摘要：{str(row['summary'] or '')[:320]}\n"
            f"引语：{str(row['key_quote'] or '')[:180]}\n"
            f"感受：{str(row['felt'] or '')[:120]}"
        )
    return "\n\n".join(parts)


def _scope_of(items: list[sqlite3.Row]) -> tuple[str, str]:
    key = str(items[0]["conversation_key"] or "") if items else ""
    if key.startswith("group:"):
        return "group", key[6:]
    if key.startswith("private:"):
        return "private", ""
    return "", ""


def _associations(conn: sqlite3.Connection, items: list[sqlite3.Row]) -> str:
    """Use the existing retrieval/association layer, not a new memory query."""
    text = " ".join(
        str(x or "") for row in items[:2] for x in (row["summary"], row["key_quote"])
    ).strip()
    if not text:
        return "（无）"
    scope, group_id = _scope_of(items)
    try:
        rows = retrieval.search_memories(
            conn, text, limit=4, scope=scope or None,
            group_id=group_id or None, include_sensitive=False,
        )
    except Exception:
        rows = []
    if not rows:
        return "（没有检索到额外的旧记忆）"
    return "\n".join(
        f"- {str(r.get('speaker') or '')}: {str(r.get('text') or '')[:220]}"
        for r in rows[:4]
    )


def _prompt(conn: sqlite3.Connection, tid: str, items: list[sqlite3.Row]) -> tuple[str, dict[str, Any]]:
    signals = episode_review._closing_signals(conn, items)
    loop = conn.execute("SELECT status,kind,one_line FROM thread_loops WHERE thread_id=?", (tid,)).fetchone()
    thread_status = str(loop["status"] if loop else "open")
    prompt = PROMPT.format(
        day=str(items[0]["day"] or "") if items else "",
        thread_status=thread_status,
        last_kind=signals.get("last_kind", "unknown"),
        last_text=str(signals.get("last_text") or "")[:400],
        has_question=bool(signals.get("has_question")),
        has_request=bool(signals.get("has_request")),
        has_ending=bool(signals.get("has_ending")),
        settled=bool(signals.get("settled")),
        segments=_segments(items),
        associations=_associations(conn, items),
    )
    return prompt, signals


def _parse(raw: str) -> dict[str, Any]:
    data = json.loads(appraise._strip_json(str(raw or "")))
    state = str(data.get("state") or "ongoing").strip().lower()
    if state not in ("resolved", "ongoing", "waiting", "abandoned"):
        state = "ongoing"
    return {
        "state": state,
        "confidence": max(0.0, min(1.0, float(data.get("confidence") or 0.0))),
        "chatter": bool(data.get("chatter")),
        "reason": str(data.get("reason") or "")[:300],
    }


def _raw_ids(items: list[sqlite3.Row]) -> list[str]:
    ids: list[str] = []
    for row in items:
        try:
            ids.extend(str(x) for x in json.loads(row["raw_ids_json"] or "[]"))
        except Exception:
            pass
    return list(dict.fromkeys(ids))


def _mark_chatter(conn: sqlite3.Connection, items: list[sqlite3.Row], now: str) -> int:
    """Keep chatter searchable, but remove its emotional/P weight."""
    ids = _raw_ids(items)
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id,importance,raw_json,consolidation_state FROM memories WHERE id IN ({marks})",
        tuple(ids),
    ).fetchall()
    changed = 0
    for row in rows:
        try:
            raw = json.loads(row["raw_json"] or "{}")
        except Exception:
            raw = {}
        if bool(raw.get("pinned")):
            continue
        if float(row["importance"] or 0) >= 0.40:
            continue
        conn.execute(
            """UPDATE memories
               SET affect_weight=0, consolidation_state='ignored',
                   consolidated_at=COALESCE(consolidated_at, ?), updated_at=?
               WHERE id=?""",
            (now, now, row["id"]),
        )
        changed += 1
    return changed


def _apply(
    conn: sqlite3.Connection,
    tid: str,
    items: list[sqlite3.Row],
    result: dict[str, Any],
    signals: dict[str, Any],
    now: str,
) -> dict[str, int]:
    stats = {"closed": 0, "archived": 0, "chatter": 0, "kept": 0}
    state = result["state"]
    conf = float(result["confidence"])
    guard = not signals.get("has_question") and not signals.get("has_request")
    if state == "resolved" and conf >= 0.75 and guard:
        conn.execute(
            """UPDATE episodes
               SET status='closed', closed_at=?, resolution_note=?,
                   closure_confidence=?, closure_source='dream-api', reviewed_at=?
               WHERE thread_id=? AND status='open'""",
            (now, result["reason"] or "dream: resolved", conf, now, tid),
        )
        stats["closed"] = len(items)
    elif state == "abandoned" and conf >= 0.80:
        conn.execute(
            """UPDATE episodes
               SET status='archived', closed_at=?, resolution_note=?,
                   closure_confidence=?, closure_source='dream-api', reviewed_at=?
               WHERE thread_id=? AND status='open'""",
            (now, result["reason"] or "dream: abandoned", conf, now, tid),
        )
        stats["archived"] = len(items)
    else:
        conn.execute(
            """UPDATE episodes
               SET closure_confidence=?, closure_source='dream-api', reviewed_at=?
               WHERE thread_id=? AND status='open'""",
            (conf, now, tid),
        )
        stats["kept"] = len(items)
    if result.get("chatter") and conf >= 0.60:
        stats["chatter"] = _mark_chatter(conn, items, now)
    return stats


def review_events(
    conn: sqlite3.Connection,
    *,
    limit: int = 12,
    timeout: int | None = None,
    chat=None,
) -> dict[str, Any]:
    """Review open event threads with the online dream API.

    `chat` is injectable for tests; production uses appraise._openai_chat.
    No local Ollama fallback is attempted.
    """
    cfg = dream_config()
    if cfg.get("enabled") is not True:
        return {"enabled": False, "skipped": "online dream review disabled"}
    if not _online(cfg):
        return {"enabled": False, "skipped": "dream provider is not online"}
    key = _api_key(cfg)
    if not key and chat is None:
        return {"enabled": True, "skipped": "api key missing"}

    rows = conn.execute(
        """SELECT * FROM episodes
           WHERE status='open'
           ORDER BY COALESCE(last_seen_at,start_at,created_at) ASC"""
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(str(row["thread_id"] or row["id"]), []).append(row)
    loop_status = {
        str(r["thread_id"]): str(r["status"] or "")
        for r in conn.execute("SELECT thread_id,status FROM thread_loops").fetchall()
    }

    def priority(pair):
        tid, items = pair
        status = loop_status.get(tid, "")
        reviewed = max((str(x["reviewed_at"] or "") for x in items), default="")
        urgent = 0 if status in ("closing", "waiting", "paused") else 1
        return (urgent, reviewed or "0000", -max(float(x["unresolved"] or 0) for x in items))

    candidates = sorted(groups.items(), key=priority)[: max(1, min(20, int(limit)))]
    stats: dict[str, Any] = {
        "enabled": True, "reviewed": 0, "closed": 0, "archived": 0,
        "chatter": 0, "kept": 0, "failed": 0, "threads": len(candidates),
        "model": str(cfg.get("model") or ""), "skipped": "",
    }
    model = str(cfg.get("model") or db.MODEL)
    base_url = str(cfg.get("base_url") or "")
    api_key = key
    timeout = int(timeout or cfg.get("timeout_s") or 180)
    for tid, items in candidates:
        now = datetime.now().astimezone().isoformat()
        try:
            prompt, signals = _prompt(conn, tid, items)
            if chat is None:
                raw, _ = appraise._openai_chat(
                    prompt, model=model, timeout=timeout, base_url=base_url,
                    api_key=api_key, temperature=0.1, max_tokens=600,
                )
            else:
                raw = chat(prompt)
            result = _parse(raw)
            applied = _apply(conn, tid, items, result, signals, now)
            conn.commit()
            stats["reviewed"] += len(items)
            for key_name in ("closed", "archived", "chatter", "kept"):
                stats[key_name] += applied[key_name]
        except Exception as exc:
            conn.rollback()
            stats["failed"] += 1
            stats["last_error"] = str(exc)[:300]
    return stats
