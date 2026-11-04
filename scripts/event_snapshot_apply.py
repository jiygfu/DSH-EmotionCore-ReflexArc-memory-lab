#!/usr/bin/env python3
"""Verify a snapshot and optionally materialize stream/event links.

Default is dry-run. Snapshots are read-only input; only ``--write`` creates
event_streams / event_memory_links / event_summaries.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from soulcore import db, event_snapshot_apply  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "soulcore.db"))
    ap.add_argument("--snapshot-id", default="")
    ap.add_argument("--min-score", type=float, default=0.65)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    conn = db.connect(args.db)
    db.init_db(conn)
    if args.snapshot_id:
        row = conn.execute("SELECT * FROM event_snapshots WHERE snapshot_id=?", (args.snapshot_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM event_snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        print(json.dumps({"ok": False, "error": "no event snapshot"}, ensure_ascii=False))
        conn.close()
        return 1
    payload = json.loads(row["payload_json"] or "{}")
    planned = event_snapshot_apply.plan(conn, payload, row["snapshot_id"], min_score=args.min_score)
    result = event_snapshot_apply.apply(conn, planned, dry_run=not args.write)
    result["snapshot_id"] = row["snapshot_id"]
    result["planned"] = planned
    print(json.dumps(result, ensure_ascii=False, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
