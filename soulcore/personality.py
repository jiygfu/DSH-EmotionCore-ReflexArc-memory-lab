"""P shadow computation for Phase 1.

P = normalize(I + sum(w_i * appraisal_i)) / (1 + sum(w_i))

This is a *shadow* readout: stored for validation, not injected into SurfCore.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import config, db

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


def compute_p(conn: sqlite3.Connection, *, prior_strength: float | None = None) -> dict[str, Any]:
    initial = db.get_meta(conn, "initial_coefficients", config.INITIAL_COEFFICIENTS)
    if not isinstance(initial, dict):
        initial = config.INITIAL_COEFFICIENTS
    prior = float(config.P_PRIOR_STRENGTH if prior_strength is None else prior_strength)
    rows = conn.execute(
        """SELECT a.dimensions_json, a.unresolved, a.confidence,
                  m.strength, m.self_relevance, m.affect_weight
           FROM appraisals a
           JOIN memories m ON m.id = a.memory_id
           WHERE a.id = (
               SELECT id FROM appraisals WHERE memory_id = a.memory_id ORDER BY id DESC LIMIT 1
           )
             AND COALESCE(m.affect_weight, 1.0) > 0"""
    ).fetchall()
    sums = {k: float(initial.get(k, 0.0)) * prior for k in DIMENSIONS}
    total_w = prior
    used = 0
    for row in rows:
        try:
            dims = json.loads(row["dimensions_json"])
        except Exception:
            continue
        w = (
            max(0.01, float(row["confidence"] or 0.0))
            * max(0.01, float(row["strength"] or 1.0))
            * max(0.01, float(row["self_relevance"] or 0.5))
            * (1.0 + 0.5 * float(row["unresolved"] or 0.0))
        )
        for k in DIMENSIONS:
            sums[k] += w * float(dims.get(k, 0.0))
        total_w += w
        used += 1
    p = {k: round(sums[k] / total_w, 4) for k in DIMENSIONS}
    return {
        "p": p,
        "memory_count": used,
        "weight_sum": round(total_w, 4),
        "initial": {k: float(initial.get(k, 0.0)) for k in DIMENSIONS},
        "prior_strength": prior,
    }


def save_p(conn: sqlite3.Connection, result: dict[str, Any]) -> None:
    now = db.utcnow()
    conn.execute(
        """INSERT INTO p_snapshots
           (ts, p_json, memory_count, weight_sum, initial_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (now, json.dumps(result["p"], ensure_ascii=False), int(result["memory_count"]),
         float(result["weight_sum"]), json.dumps(result["initial"], ensure_ascii=False), now),
    )
    conn.commit()
