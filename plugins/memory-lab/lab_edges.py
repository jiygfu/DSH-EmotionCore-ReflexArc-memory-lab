#!/usr/bin/env python3
"""Soft/hard event edges for memory-lab.

Writes only data/memory-lab.db. Reads souland episodes from soulcore.db
read-only through boundary.probe().
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import boundary  # noqa: E402
import lab_terms  # noqa: E402

WEIGHTS = {"hard": 1.0, "soft_candidate": 0.35, "current_only": 0.2}


def connect() -> sqlite3.Connection:
    c = lab_terms.connect()
    ensure(c)
    return c


def ensure(c: sqlite3.Connection) -> None:
    c.execute(
        """CREATE TABLE IF NOT EXISTS lab_edges (
          src TEXT NOT NULL,
          dst TEXT NOT NULL,
          kind TEXT NOT NULL,
          decision TEXT NOT NULL,
          weight REAL NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (src, dst, kind)
        )"""
    )
    c.commit()


def episode_ids(main: sqlite3.Connection, episode_id: str) -> list[str]:
    row = main.execute("SELECT raw_ids_json FROM episodes WHERE id=?", (episode_id,)).fetchone()
    if not row:
        return []
    try:
        return [str(x) for x in json.loads(row["raw_ids_json"] or "[]")]
    except Exception:
        return []


def sync_edges(main_db: str) -> dict:
    data = boundary.probe(main_db)
    main = boundary.connect_ro(main_db)
    own = connect()
    try:
        own.execute("DELETE FROM lab_edges")
        inserted = 0
        for pair in data["pairs"]:
            decision = pair["decision"]
            if decision not in WEIGHTS:
                continue
            left = episode_ids(main, pair["left"])
            right = episode_ids(main, pair["right"])
            if not left or not right:
                continue
            now = datetime.now().astimezone().isoformat()
            weights = WEIGHTS[decision]
            for a in left:
                for b in right:
                    if a == b:
                        continue
                    own.execute(
                        """INSERT OR REPLACE INTO lab_edges(src,dst,kind,decision,weight,updated_at)
                           VALUES (?,?,?,?,?,?)""",
                        (a, b, "event", decision, weights, now),
                    )
                    own.execute(
                        """INSERT OR REPLACE INTO lab_edges(src,dst,kind,decision,weight,updated_at)
                           VALUES (?,?,?,?,?,?)""",
                        (b, a, "event", decision, weights, now),
                    )
                    inserted += 2
        own.commit()
        return {"pairs": len(data["pairs"]), "edges": inserted, "decisions": data["counts"]}
    finally:
        own.close()
        main.close()


def neighbors(own: sqlite3.Connection, memory_id: str, *, limit: int = 4) -> list[dict]:
    try:
        rows = own.execute(
            "SELECT dst,decision,weight FROM lab_edges WHERE src=? ORDER BY weight DESC LIMIT ?",
            (str(memory_id), max(1, int(limit))),
        ).fetchall()
        return [dict(x) for x in rows]
    except Exception:
        return []


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--main-db", default=str(ROOT / "data" / "soulcore.db"))
    args = ap.parse_args()
    if args.sync:
        print(sync_edges(args.main_db))
    else:
        print("use --sync")
