#!/usr/bin/env python3
"""Ask the online model for one pre-compaction event snapshot.

The caller sends a bounded packet of recent messages (from the DSH host at
80% context pressure), not the whole session. The result is saved as a
pre-compaction snapshot and verified locally before any event link is created.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from . import appraise, config, event_snapshot

PROMPT = """你是事件快照器，不是聊天角色。现在上下文即将被压缩，请在压缩前把材料里的事件整理成 JSON。
只能使用材料中明确出现的内容，不得补造事实。

只输出：
{{"events":[{{"event_id":"可选","title":"短标题","summary":"2-4句",
"domain":"real|roleplay","participants":["..."],
"anchor_quotes":["原文中的关键句"],"commitments":["明确承诺"],
"open_items":["未完成事项"],"knowledge":["知识问题/结论"],
"confidence":0.0,"is_new":true}}]}}

规则：
- 同一事件只输出一次；不要把一句闲聊硬拆成事件；
- 跑团、情景模拟、角色扮演属于 roleplay；其中的承诺/知识只属于游戏内；
- anchor_quotes 必须逐字来自材料，便于本地回查；
- 没有把握就降低 confidence；不要编造材料里没有的信息；
- 最多输出 {event_limit} 个事件。

会话：{chat_key}
压力：{ratio}
材料：
{context}
"""


def _api_key(cfg: dict[str, Any]) -> str:
    key = appraise._api_key(cfg)
    if key:
        return key
    try:
        from . import balance
        return balance._api_key()
    except Exception:
        return ""


def _messages(payload: dict[str, Any], max_messages: int, max_chars: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    used = 0
    for item in (payload.get("messages") or [])[-max_messages:]:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("text") or item.get("content") or "").split())
        if not text:
            continue
        text = text[:4000]
        if used + len(text) > max_chars:
            text = text[: max(0, max_chars - used)]
        if not text:
            break
        out.append({"role": str(item.get("role") or "user"), "text": text})
        used += len(text)
        if used >= max_chars:
            break
    return out


def _parse(raw: str) -> list[dict[str, Any]]:
    data = json.loads(appraise._strip_json(str(raw or "")))
    events = data.get("events")
    if not isinstance(events, list):
        raise ValueError("snapshot response has no events array")
    return [x for x in events if isinstance(x, dict)]


def request_snapshot(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    chat: Any = None,
) -> dict[str, Any]:
    cfg = dict(getattr(config, "SNAPSHOT", {}))
    if cfg.get("enabled") is not True:
        return {"ok": False, "skipped": "snapshot disabled"}
    messages = _messages(
        payload,
        max(1, min(80, int(cfg.get("max_messages") or 40))),
        max(2000, min(60000, int(cfg.get("max_chars") or 24000))),
    )
    if not messages:
        return {"ok": False, "skipped": "no messages"}
    pressure = payload.get("pressure") if isinstance(payload.get("pressure"), dict) else {}
    ratio = pressure.get("ratio")
    context = "\n".join(f"[{x['role']}] {x['text']}" for x in messages)
    prompt = PROMPT.format(
        event_limit=max(1, min(50, int(cfg.get("event_limit") or 20))),
        chat_key=str(payload.get("chat_key") or payload.get("session_id") or "")[:200],
        ratio=ratio if ratio is not None else "unknown",
        context=context,
    )
    if chat is None:
        key = _api_key(cfg)
        if not key:
            return {"ok": False, "skipped": "api key missing"}
        raw, _ = appraise._openai_chat(
            prompt,
            model=str(cfg.get("model") or "deepseek-flash"),
            timeout=int(cfg.get("timeout_s") or 180),
            base_url=str(cfg.get("base_url") or "https://api.deepseek.com"),
            api_key=key,
            temperature=0.1,
            max_tokens=1400,
        )
    else:
        raw = chat(prompt)
    events = _parse(raw)
    snapshot = {
        "session_id": payload.get("session_id"),
        "chat_key": payload.get("chat_key"),
        "captured_at": payload.get("captured_at"),
        "trigger": payload.get("trigger") or "context_pressure_80",
        "pressure": pressure,
        "events": events,
    }
    saved = event_snapshot.save(conn, snapshot)
    return {"ok": True, "snapshot": saved, "messages": len(messages), "events": len(events)}
