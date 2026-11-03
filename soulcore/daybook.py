"""Daily baseline / cleaned cumulative offset ledger.

The day starts with a baseline P captured before the day's appraisals.
After consolidation (sleep cleaning), the cleaned P is compared with that
baseline; the per-dimension difference is the day's cumulative offset.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from . import db, personality

DIMENSIONS = personality.DIMENSIONS


def today_key() -> str:
    return datetime.now().astimezone().date().isoformat()


def ensure_day_baseline(
    conn: sqlite3.Connection,
    *,
    day: str | None = None,
) -> dict[str, Any]:
    key = day or today_key()
    row = conn.execute("SELECT * FROM daily_summaries WHERE day_key=?", (key,)).fetchone()
    if row:
        return dict(row)
    p = personality.compute_p(conn)
    now = db.utcnow()
    conn.execute(
        """INSERT INTO daily_summaries
           (day_key, baseline_json, baseline_memory_count, baseline_weight_sum,
            baseline_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (key, json.dumps(p["p"], ensure_ascii=False), int(p["memory_count"]),
         float(p["weight_sum"]), now, now, now),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM daily_summaries WHERE day_key=?", (key,)).fetchone())


def finalize_day(
    conn: sqlite3.Connection,
    *,
    day: str | None = None,
    ambient: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = day or today_key()
    ensure_day_baseline(conn, day=key)
    row = conn.execute("SELECT * FROM daily_summaries WHERE day_key=?", (key,)).fetchone()
    if not row:
        raise RuntimeError("daily baseline missing")
    try:
        baseline = json.loads(row["baseline_json"] or "{}")
    except Exception:
        baseline = {}
    current = personality.compute_p(conn)
    end = current["p"]
    delta = {k: round(float(end.get(k, 0.0)) - float(baseline.get(k, 0.0)), 4) for k in DIMENSIONS}
    cons = conn.execute(
        """SELECT kept, ignored FROM consolidation_runs
           WHERE day_key=? ORDER BY id DESC LIMIT 1""",
        (key,),
    ).fetchone()
    kept = int(cons["kept"] or 0) if cons else 0
    ignored = int(cons["ignored"] or 0) if cons else 0
    now = db.utcnow()
    conn.execute(
        """UPDATE daily_summaries SET
             end_json=?, delta_json=?, end_at=?, kept=?, ignored=?, ambient_json=?, updated_at=?
           WHERE day_key=?""",
        (json.dumps(end, ensure_ascii=False), json.dumps(delta, ensure_ascii=False),
         now, kept, ignored,
         json.dumps(ambient or {}, ensure_ascii=False), now, key),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM daily_summaries WHERE day_key=?", (key,)).fetchone())


def latest(conn: sqlite3.Connection, day: str | None = None) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM daily_summaries WHERE day_key=? ORDER BY id DESC LIMIT 1",
        (day or today_key(),),
    ).fetchone()
    if not row:
        return None
    out = dict(row)
    for key in ("baseline_json", "end_json", "delta_json", "ambient_json"):
        try:
            out[key.replace("_json", "")] = json.loads(out.pop(key) or "null")
        except Exception:
            out[key.replace("_json", "")] = None
    return out
