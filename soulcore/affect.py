"""Affect aggregation for SoulCore Phase 1.

This is *not* the personality vector P. It is a current affective readout over
the most recent appraised memories, used for Phase 1 validation only.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import db

DIMENSIONS = [
    "security",
    "trust",
    "self_efficacy",
    "caution",
    "sociability",
    "openness",
    "valence",
    "arousal",
]


def _weighted_mean(rows: list[tuple[dict[str, float], float]], key: str) -> float:
    total = sum(w for _, w in rows)
    if total <= 0:
        return 0.0
    return sum(d.get(key, 0.0) * w for d, w in rows) / total


def compute_affect(conn: sqlite3.Connection, window: int = 20) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT a.dimensions_json, a.unresolved, a.confidence, m.strength
           FROM appraisals a JOIN memories m ON m.id = a.memory_id
           WHERE COALESCE(m.affect_weight, 1.0) > 0
           ORDER BY a.id DESC LIMIT ?""",
        (max(1, int(window)),),
    ).fetchall()
    parsed: list[tuple[dict[str, float], float]] = []
    for r in rows:
        try:
            dims = json.loads(r["dimensions_json"])
            if not isinstance(dims, dict):
                continue
            weight = max(0.01, float(r["confidence"] or 0.0) * float(r["strength"] or 1.0))
            parsed.append((dims, weight))
        except Exception:
            continue
    if not parsed:
        result = {k: 0.0 for k in DIMENSIONS}
        result.update({"stress": 0.0, "unresolved": 0.0, "memory_count": 0})
        return result

    means = {k: round(_weighted_mean(parsed, k), 4) for k in DIMENSIONS}
    unresolved = round(
        sum(float(r["unresolved"] or 0.0) * max(0.01, float(r["confidence"] or 0.0) * float(r["strength"] or 1.0))
            for r in rows) / max(0.01, sum(
                max(0.01, float(r["confidence"] or 0.0) * float(r["strength"] or 1.0)) for r in rows
            )),
        4,
    )
    stress = round(
        0.35 * (1.0 - means["security"])
        + 0.25 * means["caution"]
        + 0.20 * unresolved
        + 0.20 * (1.0 - means["self_efficacy"]),
        4,
    )
    result = dict(means)
    result.update({
        "stress": stress,
        "unresolved": unresolved,
        "memory_count": len(parsed),
    })
    return result


def save_snapshot(conn: sqlite3.Connection, affect: dict[str, Any]) -> None:
    now = db.utcnow()
    conn.execute(
        """INSERT INTO affect_snapshots
           (ts, valence, arousal, stress, unresolved, memory_count, appraiser_id, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (now, float(affect.get("valence", 0.0)), float(affect.get("arousal", 0.0)),
         float(affect.get("stress", 0.0)), float(affect.get("unresolved", 0.0)),
         int(affect.get("memory_count", 0)), db.APPRAISER_ID,
         json.dumps(affect, ensure_ascii=False), now),
    )
    conn.commit()


def latest(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM affect_snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None
