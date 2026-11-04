#!/usr/bin/env python3
"""Ingest a pre-compaction event snapshot produced by the API.

The API should emit this *before* native compaction, while the current context
still contains the event. This module only validates and stores the snapshot;
it does not merge events, call a model, or change L5.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any

MAX_EVENTS = 100

ALLOWED_DOMAINS = {"real", "roleplay"}
ALLOWED_TRIGGERS = {"context_pressure_80", "manual", "pre_compaction"}


def _clean(value: Any, limit: int = 2000) -> str:
    s = " ".join(str(value or "").split())
    return s[:limit]


def _ratio(pressure: dict[str, Any]) -> float | None:
    try:
        p = float(pressure.get("pressureTokens") or 0)
        w = float(pressure.get("contextWindow") or 0)
        return round(p / w, 4) if p > 0 and w > 0 else None
    except Exception:
        return None


def normalize(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("snapshot must be an object")
    events_raw = payload.get("events")
    if not isinstance(events_raw, list):
        raise ValueError("events must be an array")
    events: list[dict[str, Any]] = []
    for item in events_raw[:MAX_EVENTS]:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "real").lower()
        if domain not in ALLOWED_DOMAINS:
            domain = "real"
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence") or 0.0)))
        except Exception:
            confidence = 0.0
        events.append({
            "event_id": _clean(item.get("event_id") or "", 120),
            "stream_id": _clean(item.get("stream_id") or "", 120),
            "title": _clean(item.get("title") or "", 200),
            "summary": _clean(item.get("summary") or "", 1200),
            "domain": domain,
            "participants": [str(x)[:80] for x in (item.get("participants") or []) if str(x)][:20],
            "anchor_quotes": [_clean(x, 300) for x in (item.get("anchor_quotes") or []) if str(x)][:10],
            "commitments": [_clean(x, 300) for x in (item.get("commitments") or []) if str(x)][:10],
            "open_items": [_clean(x, 300) for x in (item.get("open_items") or []) if str(x)][:10],
            "knowledge": [_clean(x, 300) for x in (item.get("knowledge") or []) if str(x)][:10],
            "confidence": confidence,
            "is_new": bool(item.get("is_new")),
        })
    pressure = payload.get("pressure") if isinstance(payload.get("pressure"), dict) else {}
    trigger = str(payload.get("trigger") or "pre_compaction")
    if trigger not in ALLOWED_TRIGGERS:
        trigger = "pre_compaction"
    captured = str(payload.get("captured_at") or datetime.now().astimezone().isoformat())
    session_id = _clean(payload.get("session_id") or "", 120)
    chat_key = _clean(payload.get("chat_key") or "", 200)
    raw = json.dumps(payload, ensure_ascii=False)
    sid = "es_" + hashlib.sha1(
        f"{session_id}|{chat_key}|{captured}|{raw}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "snapshot_id": sid,
        "session_id": session_id,
        "chat_key": chat_key,
        "captured_at": captured,
        "trigger": trigger,
        "pressure_tokens": pressure.get("pressureTokens"),
        "context_window": pressure.get("contextWindow"),
        "ratio": _ratio(pressure),
        "events": events,
        "raw": raw,
    }


def save(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    data = normalize(payload)
    conn.execute(
        """INSERT OR REPLACE INTO event_snapshots
           (snapshot_id,session_id,chat_key,captured_at,trigger,pressure_tokens,
            context_window,ratio,event_count,payload_json,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data["snapshot_id"], data["session_id"], data["chat_key"], data["captured_at"],
            data["trigger"], data["pressure_tokens"], data["context_window"], data["ratio"],
            len(data["events"]), data["raw"], datetime.now().astimezone().isoformat(),
        ),
    )
    conn.commit()
    return {
        "ok": True,
        "snapshot_id": data["snapshot_id"],
        "events": len(data["events"]),
        "domain_counts": {
            "real": sum(1 for x in data["events"] if x["domain"] == "real"),
            "roleplay": sum(1 for x in data["events"] if x["domain"] == "roleplay"),
        },
        "ratio": data["ratio"],
    }
