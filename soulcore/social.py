"""Read-only social relationship shadow.

Person relationships are derived from person-specific appraisals. This module
does not feed P directly; it is a shadow summary for later injection.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any


def compute(conn: sqlite3.Connection, *, day: str | None = None, limit: int = 8) -> dict[str, Any]:
    d = day or datetime.now().astimezone().date().isoformat()
    rows = conn.execute(
        """SELECT id, display_name, message_count, familiarity, trust, valence,
                  unresolved, stance, action_hint, profile_status, profile_version
           FROM people WHERE message_count > 0
           ORDER BY message_count DESC LIMIT ?""",
        (max(1, int(limit)),),
    ).fetchall()
    if not rows:
        return {
            "day": d, "people_count": 0, "weighted_trust": 0.0,
            "weighted_valence": 0.0, "unresolved": 0.0, "stances": {}, "people": [],
        }
    total_w = sum(max(0.1, float(r["familiarity"] or 0.0)) for r in rows)
    trust = sum(float(r["trust"] or 0.0) * max(0.1, float(r["familiarity"] or 0.0)) for r in rows) / total_w
    valence = sum(float(r["valence"] or 0.0) * max(0.1, float(r["familiarity"] or 0.0)) for r in rows) / total_w
    unresolved = sum(float(r["unresolved"] or 0.0) * max(0.1, float(r["familiarity"] or 0.0)) for r in rows) / total_w
    stances: dict[str, int] = {}
    for r in rows:
        stances[r["stance"] or "casual"] = stances.get(r["stance"] or "casual", 0) + 1
    return {
        "day": d,
        "people_count": len(rows),
        "weighted_trust": round(trust, 4),
        "weighted_valence": round(valence, 4),
        "unresolved": round(unresolved, 4),
        "stances": stances,
        "people": [dict(r) for r in rows],
    }
