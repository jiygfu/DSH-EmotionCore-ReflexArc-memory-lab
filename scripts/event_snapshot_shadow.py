#!/usr/bin/env python3
"""Read-only shadow: verify an API event snapshot against raw memories."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from soulcore import event_snapshot_bind  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "soulcore.db"))
    ap.add_argument("--snapshot-id", default="")
    ap.add_argument("--out-dir", default=str(ROOT / "reports"))
    args = ap.parse_args()

    conn = sqlite3.connect("file:" + args.db + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    if args.snapshot_id:
        row = conn.execute("SELECT * FROM event_snapshots WHERE snapshot_id=?", (args.snapshot_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM event_snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        print(json.dumps({"ok": False, "error": "no event snapshot"}, ensure_ascii=False))
        return 1
    payload = json.loads(row["payload_json"] or "{}")
    day = str(row["captured_at"] or "")[:10]
    for event in payload.get("events") or []:
        if isinstance(event, dict) and not event.get("day"):
            event["day"] = day
    result = event_snapshot_bind.bind_payload(conn, payload)
    conn.close()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"event-snapshot-bind-{row['snapshot_id']}"
    (base.with_suffix(".json")).write_text(
        json.dumps({"snapshot_id": row["snapshot_id"], "day": day, "bindings": result}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        f"# Event snapshot binding: {row['snapshot_id']}", "",
        f"- day: {day}",
        f"- events: {len(result)}",
        "", "> 只读校验；没有调用云端 API，没有写事件绑定。", "",
        "| event | domain | status | best | exact | memory | summary |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for b in result:
        best = (b.get("candidates") or [{}])[0]
        lines.append(
            f"| {b['event_id'] or '-'} | {b['domain']} | {b['status']} | {b['best_score']:.2f} | "
            f"{'是' if best.get('exact_quote') else '否'} | {best.get('memory_id') or '-'} | {str(b.get('summary') or '')[:70]} |"
        )
    (base.with_suffix(".md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True, "snapshot_id": row["snapshot_id"],
        "json": str(base.with_suffix(".json")), "md": str(base.with_suffix(".md")),
        "events": len(result), "verified": sum(1 for x in result if x["verified"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
