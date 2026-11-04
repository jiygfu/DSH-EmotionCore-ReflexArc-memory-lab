#!/usr/bin/env python3
"""Turn a verified pre-compaction snapshot into local event links.

The snapshot is a *claim*. This module verifies its anchor quotes against raw
memories, then (optionally) writes only verified links. Default is dry-run.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any

from . import event_snapshot_bind


def _stream_id(snapshot_id: str, event: dict[str, Any]) -> str:
    raw = f"{snapshot_id}|{event.get('event_id') or ''}|{event.get('title') or ''}"
    return "stream_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def plan(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    snapshot_id: str = "",
    *,
    min_score: float = 0.65,
) -> dict[str, Any]:
    events = [event for event in (payload.get("events") or []) if isinstance(event, dict)]
    bindings = event_snapshot_bind.bind_payload(conn, {"events": events})
    streams: list[dict[str, Any]] = []
    for event, binding in zip(events, bindings):
        candidates = [c for c in binding.get("candidates") or [] if float(c.get("score") or 0) >= min_score]
        if not candidates:
            continue
        best = candidates[0]
        roleplay = str(event.get("domain") or "real") == "roleplay"
        streams.append({
            "stream_id": _stream_id(snapshot_id, event),
            "snapshot_id": snapshot_id,
            "thread_id": str(event.get("stream_id") or ""),
            "title": str(event.get("title") or "")[:200],
            "summary": str(event.get("summary") or "")[:1200],
            "domain": "roleplay" if roleplay else "real",
            "confidence": float(event.get("effective_confidence") if event.get("effective_confidence") is not None else event.get("confidence") or 0),
            "reference_weight": 0.60 if roleplay else 1.0,
            "personality_eligible": not roleplay,
            "verified": bool(binding.get("verified")),
            "best_memory_id": best["memory_id"],
            "links": candidates[:3],
        })
    return {"snapshot_id": snapshot_id, "streams": streams}


def apply(conn: sqlite3.Connection, planned: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "dry_run": True, "streams": len(planned.get("streams") or []),
                "links": sum(len(x.get("links") or []) for x in (planned.get("streams") or []))}
    now = datetime.now().astimezone().isoformat()
    for stream in planned.get("streams") or []:
        conn.execute(
            """INSERT INTO event_streams
               (stream_id,snapshot_id,thread_id,title,summary,domain,confidence,
                reference_weight,personality_eligible,verified,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(stream_id) DO UPDATE SET
                 snapshot_id=excluded.snapshot_id, thread_id=excluded.thread_id,
                 title=excluded.title, summary=excluded.summary, domain=excluded.domain,
                 confidence=excluded.confidence, reference_weight=excluded.reference_weight,
                 personality_eligible=excluded.personality_eligible,
                 verified=excluded.verified, updated_at=excluded.updated_at""",
            (
                stream["stream_id"], stream["snapshot_id"], stream["thread_id"],
                stream["title"], stream["summary"], stream["domain"], stream["confidence"],
                stream["reference_weight"], 1 if stream["personality_eligible"] else 0,
                1 if stream["verified"] else 0, now, now,
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO event_summaries(stream_id,summary,source,created_at) VALUES (?,?,?,?)",
            (stream["stream_id"], stream["summary"], "api_precompaction_snapshot", now),
        )
        for link in stream.get("links") or []:
            conn.execute(
                """INSERT OR REPLACE INTO event_memory_links
                   (stream_id,memory_id,role,score,exact_quote,evidence,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    stream["stream_id"], link["memory_id"], "anchor",
                    link.get("score"), 1 if link.get("exact_quote") else 0,
                    str(link.get("text") or "")[:300], now,
                ),
            )
    conn.commit()
    return {"ok": True, "dry_run": False, "streams": len(planned.get("streams") or []),
            "links": sum(len(x.get("links") or []) for x in (planned.get("streams") or []))}
