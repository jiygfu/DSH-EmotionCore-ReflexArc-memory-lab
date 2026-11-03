"""Sleep / dream consolidation for Phase 1.

At day end:
  - include all of today's important memories;
  - randomly surface a budgeted sample of memories not triggered today;
  - write a dream run + P shadow snapshot.

No LLM call and no SurfCore write. This is deterministic except for the
seeded random sample.
"""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime
from typing import Any

from . import db, diary, personality


def _day(value: str | None) -> str:
    return value or datetime.now().astimezone().date().isoformat()


def run(
    conn: sqlite3.Connection,
    *,
    day: str | None = None,
    budget: int = 12,
    seed: int | None = None,
    write_diary: bool = False,
    diary_model: str = db.MODEL,
) -> dict[str, Any]:
    d = _day(day)
    budget = max(1, int(budget))
    today = conn.execute(
        """SELECT * FROM memories
           WHERE consolidation_state = 'kept'
             AND (
               substr(COALESCE(ts, created_at), 1, 10) = ?
               OR substr(COALESCE(last_triggered_at, ''), 1, 10) = ?
             )
           ORDER BY COALESCE(last_triggered_at, ts, created_at) DESC""",
        (d, d),
    ).fetchall()
    today_ids = {r["id"] for r in today}
    candidates = conn.execute(
        """SELECT * FROM memories
           WHERE COALESCE(last_triggered_at, '') NOT LIKE ?
           ORDER BY id""",
        (d + "%",),
    ).fetchall()
    need = max(0, budget - len(today))
    rng = random.Random(seed)
    picked: list[sqlite3.Row] = []
    pool = [r for r in candidates if r["id"] not in today_ids]
    while pool and len(picked) < need:
        # Weight by importance and strength; rare memories still have a chance.
        weights = [
            max(0.05, float(r["importance"] or 0.0))
            + 0.20
            + 0.10 * float(r["strength"] or 1.0)
            for r in pool
        ]
        total = sum(weights)
        x = rng.random() * total
        acc = 0.0
        chosen = pool[-1]
        for r, w in zip(pool, weights):
            acc += w
            if x <= acc:
                chosen = r
                break
        picked.append(chosen)
        pool = [r for r in pool if r["id"] != chosen["id"]]

    p_result = personality.compute_p(conn)
    now = db.utcnow()
    cur = conn.execute(
        """INSERT INTO dream_runs (day_key, budget, sampled, p_json, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (d, budget, len(today) + len(picked),
         json.dumps(p_result["p"], ensure_ascii=False),
         json.dumps({"today": len(today), "random": len(picked), "seed": seed}, ensure_ascii=False),
         now),
    )
    dream_id = int(cur.lastrowid)
    for r in today:
        conn.execute(
            """INSERT INTO dream_items (dream_id, memory_id, reason, created_at)
               VALUES (?, ?, 'today_important', ?)""",
            (dream_id, r["id"], now),
        )
    for r in picked:
        conn.execute(
            """INSERT INTO dream_items (dream_id, memory_id, reason, created_at)
               VALUES (?, ?, 'random_untriggered', ?)""",
            (dream_id, r["id"], now),
        )
    personality.save_p(conn, p_result)
    conn.commit()
    diary_result = None
    if write_diary:
        diary_result = diary.generate(
            conn, dream_id=dream_id, day=d, p=p_result["p"], model=diary_model
        )
    return {
        "day_key": d,
        "budget": budget,
        "today_important": len(today),
        "random_untriggered": len(picked),
        "sampled": len(today) + len(picked),
        "p": p_result["p"],
        "p_memory_count": p_result["memory_count"],
        "dream_id": dream_id,
        "diary": diary_result,
    }
