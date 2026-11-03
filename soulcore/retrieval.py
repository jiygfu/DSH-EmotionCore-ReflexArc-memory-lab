"""Cheap pre-send / idle retrieval for familiarity.

Given text that is about to go to the speaking API, find long-term memories
that resonate with it, mark them as triggered today, and update:

  - current_familiarity
  - processing_fluency

No LLM call. This is the "subconscious recognition" layer.
"""

from __future__ import annotations

import math
import re
import sqlite3
from typing import Any

from . import db


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_QUERY_SPLIT_RE = re.compile(r"[\s,，。.!！?？;；:：/\\|]+")


def _query_terms(query: str, *, max_terms: int = 16) -> list[str]:
    """Chinese has no spaces; use 2-char shingles for FTS/LIKE fallback."""
    terms: list[str] = []
    for token in _QUERY_SPLIT_RE.split(query or ""):
        token = token.strip()
        if not token:
            continue
        if _CJK_RE.search(token):
            if len(token) <= 2:
                terms.append(token)
            else:
                terms.extend(token[i:i + 2] for i in range(len(token) - 1))
        else:
            terms.append(token)
    out: list[str] = []
    for term in terms:
        if term not in out:
            out.append(term)
        if len(out) >= max_terms:
            break
    return out


def _fts_query(query: str) -> str:
    terms = _query_terms(query)
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)


def search_memories(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 10,
    scope: str | None = None,
    group_id: str | None = None,
    person_id: str | None = None,
    include_sensitive: bool = False,
    include_reflections: bool = False,
) -> list[dict[str, Any]]:
    """FTS5-first memory search; degrade to local 2-gram ranking.

    Kept separate from ``retrieve``: familiarity/trigger tracking must not be
    narrowed by a full-text prefilter. ``reflection``/``legacy_prompt`` rows
    stay in the raw store but are excluded from the default evidence surface.
    """
    query = (query or "").strip()
    if not query:
        return []
    where = [] if include_sensitive else ["m.sensitive=0"]
    params: list[Any] = []
    if not include_reflections:
        where.append("m.status='active'")
    if scope:
        where.append("m.scope=?")
        params.append(scope)
    if group_id:
        where.append("m.group_id=?")
        params.append(group_id)
    if person_id:
        where.append("m.person_id=?")
        params.append(person_id)
    where.append("memories_fts MATCH ?")
    where_sql = "WHERE " + " AND ".join(where)
    rows: list[sqlite3.Row] = []
    try:
        rows = conn.execute(
            f"""SELECT m.* FROM memories_fts f
                JOIN memories m ON m.id=f.memory_id
                {where_sql}
                ORDER BY bm25(memories_fts) ASC
                LIMIT ?""",
            (*params, _fts_query(query), max(20, int(limit) * 8)),
        ).fetchall()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        rows = []
    if not rows:
        fallback_where = [w for w in where if w != "memories_fts MATCH ?"]
        fallback_sql = ("WHERE " + " AND ".join(fallback_where)) if fallback_where else ""
        rows = conn.execute(
            f"SELECT m.* FROM memories m {fallback_sql} ORDER BY COALESCE(m.ts,m.created_at) DESC LIMIT 2000",
            tuple(params),
        ).fetchall()
    scored: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        sim = _similarity(query, row["text"])
        if sim <= 0:
            continue
        importance = max(0.0, float(row["importance"] or 0.0))
        scored.append((0.82 * sim + 0.18 * importance, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    seen: set[str] = set()
    for score, row in scored:
        norm = "".join(str(row["text"] or "").split()).lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append({
            "id": row["id"],
            "score": round(score, 4),
            "similarity": _similarity(query, row["text"]),
            "scope": row["scope"],
            "speaker": row["speaker"],
            "person_id": row["person_id"],
            "identity_status": row["identity_status"] or "unknown",
            "status": row["status"] or "active",
            "ts": row["ts"],
            "text": row["text"],
        })
        if len(out) >= max(1, int(limit)):
            break
    return out


def _grams(text: str, n: int = 2) -> set[str]:
    s = "".join(ch.lower() for ch in str(text) if not ch.isspace())
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _similarity(query: str, text: str) -> float:
    q = _grams(query)
    t = _grams(text)
    if not q or not t:
        return 0.0
    overlap = len(q & t)
    contain = overlap / max(1, len(q))
    jaccard = overlap / max(1, len(q | t))
    return round(0.65 * contain + 0.35 * jaccard, 4)


def retrieve(
    conn: sqlite3.Connection,
    text: str,
    *,
    limit: int = 8,
    min_similarity: float = 0.12,
    mark: bool = True,
    include_sensitive: bool = False,
    include_text: bool = False,
    source: str = "pre_send",
) -> list[dict[str, Any]]:
    """Return top matching memories; optionally update familiarity/trigger."""
    query = (text or "").strip()
    if not query:
        return []
    where = "WHERE sensitive=0" if not include_sensitive else ""
    rows = conn.execute(f"SELECT * FROM memories {where}").fetchall()
    scored: list[tuple[float, float, sqlite3.Row]] = []
    for row in rows:
        sim = _similarity(query, row["text"])
        if sim <= 0:
            continue
        importance = max(0.0, float(row["importance"] or 0.0))
        fam = max(0.0, min(1.0, float(row["current_familiarity"] or 0.0)))
        # familiarity helps recognition, but must not drown out actual match.
        rank = 0.78 * sim + 0.12 * fam + 0.10 * importance
        scored.append((rank, sim, row))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top = scored[: max(1, int(limit))]

    out: list[dict[str, Any]] = []
    hit_ids: list[str] = []
    for rank, sim, row in top:
        hit = sim >= min_similarity
        before = float(row["current_familiarity"] or 0.0)
        after = before
        fluency = float(row["processing_fluency"] or 0.0)
        if hit and mark:
            # asymptotic: repeated recall gets familiar, never exceeds 1.
            after = min(1.0, before + 0.25 * sim * (1.0 - before))
            fluency = round(0.55 * after + 0.45 * sim, 4)
            conn.execute(
                """UPDATE memories
                   SET current_familiarity=?, processing_fluency=?, updated_at=?
                   WHERE id=?""",
                (round(after, 4), fluency, db.utcnow(), row["id"]),
            )
            hit_ids.append(row["id"])
        item: dict[str, Any] = {
            "id": row["id"],
            "score": round(rank, 4),
            "similarity": sim,
            "familiarity_before": round(before, 4),
            "familiarity_after": round(after, 4),
            "fluency": round(fluency, 4),
            "hit": hit,
            "scope": row["scope"],
            "person_id": row["person_id"],
            "speaker": row["speaker"],
            "identity_status": row["identity_status"] or "unknown",
        }
        if include_text:
            item["text"] = row["text"]
        out.append(item)
    if mark and hit_ids:
        db.mark_triggered(conn, hit_ids, source=source, note=query[:120])
    else:
        conn.commit()
    return out


def idle_retrieve(conn: sqlite3.Connection, text: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Idle variant: same cheap retrieval, lower trigger label."""
    return retrieve(conn, text, limit=limit, mark=True, source="idle_retrieval")
