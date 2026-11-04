#!/usr/bin/env python3
"""Local verification of API pre-compaction event snapshots.

The API gives claim-level events with anchor quotes. This module maps those
quotes back to the local raw memories and reports a verification score. It does
not write links or call a cloud model.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from . import event_streams, retrieval


def _norm(text: Any) -> str:
    s = str(text or "").lower()
    s = re.sub(r"[\s\W_]+", "", s, flags=re.UNICODE)
    return s


def _tokens(text: Any) -> set[str]:
    return event_streams._tokens(str(text or ""))


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def _recency(ts: Any, event_day: str) -> float:
    try:
        d = date.fromisoformat(str(ts)[:10])
        base = date.fromisoformat(event_day) if event_day else date.today()
        return max(0.0, 1.0 - max(0, (base - d).days) / 45.0)
    except Exception:
        return 0.0


def bind_event(conn, event: dict[str, Any], *, limit: int = 5) -> dict[str, Any]:
    queries = [str(x) for x in (event.get("anchor_quotes") or []) if str(x)]
    if not queries:
        queries = [str(event.get("summary") or "")]
    queries = [q for q in queries if q.strip()][:6]
    summary = str(event.get("summary") or "")
    stoks = _tokens(summary)
    event_day = str(event.get("day") or date.today().isoformat())
    candidates: dict[str, dict[str, Any]] = {}
    for q in queries:
        try:
            hits = retrieval.search_memories(
                conn, q, limit=max(5, limit * 2),
                include_sensitive=False, include_reflections=False,
            )
        except Exception:
            hits = []
        nq = _norm(q)
        for h in hits:
            text = str(h.get("text") or "")
            nt = _norm(text)
            exact = 1.0 if nq and (nq in nt or nt in nq) else 0.0
            overlap = _overlap(_tokens(q), _tokens(text))
            emb = 0.0
            try:
                vecs = event_streams._embed([q, text])
                if vecs and len(vecs) == 2:
                    emb = max(0.0, min(1.0, (event_streams._cosine(vecs[0], vecs[1]) - 0.35) / 0.65))
            except Exception:
                emb = 0.0
            rec = _recency(h.get("ts"), event_day)
            score = 0.50 * exact + 0.25 * overlap + 0.15 * emb + 0.10 * rec
            mid = str(h.get("id") or "")
            if not mid:
                continue
            prev = candidates.get(mid)
            if prev is None or score > prev["score"]:
                candidates[mid] = {
                    "memory_id": mid,
                    "score": round(score, 3),
                    "exact_quote": bool(exact),
                    "text_overlap": round(overlap, 3),
                    "embedding_similarity": round(emb, 3),
                    "recency": round(rec, 3),
                    "text": text[:300],
                    "speaker": h.get("speaker"),
                    "ts": h.get("ts"),
                }
    ranked = sorted(candidates.values(), key=lambda x: x["score"], reverse=True)[:limit]
    best = ranked[0]["score"] if ranked else 0.0
    return {
        "event_id": event.get("event_id") or "",
        "domain": event.get("domain") or "real",
        "summary": summary[:300],
        "candidates": ranked,
        "best_score": best,
        "verified": bool(ranked and best >= 0.65 and (ranked[0]["exact_quote"] or ranked[0]["score"] >= 0.78)),
        "status": "verified" if ranked and best >= 0.65 else ("weak" if ranked else "unmatched"),
    }


def bind_payload(conn, payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [bind_event(conn, event) for event in (payload.get("events") or []) if isinstance(event, dict)]
