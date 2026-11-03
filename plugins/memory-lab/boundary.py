#!/usr/bin/env python3
"""Read-only event-boundary probe for memory-lab.

Compares the current thread assignment with a stricter adjacent-episode rule.
Never writes to soulcore.db.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ENDING = re.compile(r"(晚安|拜拜|再见|886|先这样|先撤|溜了|去忙|下了|睡了|不聊了|回头聊|改天聊|明天聊|下次聊|到此为止)")
SETTLED = re.compile(r"(说好了|就这么定|扯平|一言为定|成交|定了|好啦|行啦|算啦|先这样|以后再说|下次再说|不说了|不提了|到此为止|翻篇)")
QUESTION = re.compile(r"([?？]\s*$|(吗|嘛|么|咋|怎么|为什么|为啥|什么|哪个|哪里|哪儿|谁|多少|几点|是不是|有没有|能不能|可不可以|要不要|好不好|对不对|行不行)\s*[。！!…～~]*$)")
REQUEST = re.compile(r"(帮我|帮忙|麻烦你|请你|教我|告诉我|说说|讲讲|发我|给我|推荐|查一下|搜一下|找一下|看一下|写一个|弄一个|来个|整一个)")


def connect_ro(path: str) -> sqlite3.Connection:
    uri = "file:" + str(Path(path).resolve()).replace("\\", "/") + "?mode=ro"
    c = sqlite3.connect(uri, uri=True)
    c.row_factory = sqlite3.Row
    return c


def parse(ts) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d.astimezone()
    except Exception:
        return None


def grams(s: str) -> set[str]:
    x = re.sub(r"[\s\W_]+", "", str(s or ""))
    return {x[i:i + 2] for i in range(max(0, len(x) - 1))}


def overlap(a: str, b: str) -> float:
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / max(1, len(ga | gb))


def kind_of(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return "silence"
    if ENDING.search(t) and len(t) <= 30:
        return "ending"
    if QUESTION.search(t):
        return "question"
    if REQUEST.search(t):
        return "request"
    if SETTLED.search(t):
        return "settled"
    return "substantive"


def last_text(conn, row) -> str:
    try:
        ids = json.loads(row["raw_ids_json"] or "[]")
    except Exception:
        ids = []
    if not ids:
        return ""
    marks = ",".join("?" for _ in ids)
    got = conn.execute(
        f"SELECT text FROM memories WHERE id IN ({marks}) ORDER BY COALESCE(ts,created_at) DESC LIMIT 1",
        tuple(ids),
    ).fetchone()
    return str(got["text"] if got else "")


def probe(db: str) -> dict:
    c = connect_ro(db)
    try:
        rows = c.execute("SELECT * FROM episodes ORDER BY conversation_key, COALESCE(start_at,created_at), id").fetchall()
        out = []
        for a, b in zip(rows, rows[1:]):
            if str(a["conversation_key"] or "") != str(b["conversation_key"] or ""):
                continue
            sa, sb = parse(a["end_at"] or a["start_at"]), parse(b["start_at"])
            if not sa or not sb:
                continue
            gap = max(0.0, (sb - sa).total_seconds() / 3600)
            text_a = f"{a['summary'] or ''} {a['key_quote'] or ''} {a['felt'] or ''}"
            text_b = f"{b['summary'] or ''} {b['key_quote'] or ''} {b['felt'] or ''}"
            ov = overlap(text_a, text_b)
            ka = kind_of(last_text(c, a))
            same_thread = str(a["thread_id"] or "") == str(b["thread_id"] or "")
            # Proposed boundary rule: stricter than the current same-thread rule.
            proposed = False
            why = []
            if gap > 72:
                proposed = False; why.append("gap>72h")
            elif ka in ("ending", "settled"):
                proposed = False; why.append(f"previous={ka}")
            elif gap <= 1.5 and ov >= 0.02:
                proposed = True; why.append("short-gap+overlap")
            elif gap <= 36 and ov >= 0.12:
                proposed = True; why.append("loose-overlap")
            elif gap <= 72 and ov >= 0.22:
                proposed = True; why.append("strong-overlap")
            else:
                proposed = False; why.append("weak-continuity")
            decision = "separate"
            if same_thread and proposed:
                decision = "hard"
            elif proposed:
                decision = "soft_candidate"
            elif same_thread:
                decision = "current_only"
            out.append({
                "left": a["id"], "right": b["id"], "decision": decision,
                "conversation": a["conversation_key"],
                "left_day": a["day"], "right_day": b["day"],
                "left_start": a["start_at"], "right_start": b["start_at"],
                "gap_hours": round(gap, 2),
                "overlap": round(ov, 3),
                "left_last_kind": ka,
                "current_same_thread": same_thread,
                "proposed_same_thread": proposed,
                "why": why,
                "left_summary": str(a["summary"] or "")[:160],
                "right_summary": str(b["summary"] or "")[:160],
            })
        return {"pairs": out, "counts": {
            "pairs": len(out),
            "current_merged": sum(1 for x in out if x["current_same_thread"]),
            "proposed_merged": sum(1 for x in out if x["proposed_same_thread"]),
            "current_only": sum(1 for x in out if x["current_same_thread"] and not x["proposed_same_thread"]),
            "proposed_only": sum(1 for x in out if x["proposed_same_thread"] and not x["current_same_thread"]),
        }}
    finally:
        c.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "soulcore.db"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    data = probe(args.db)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(data["counts"])
        for x in data["pairs"]:
            if x["current_same_thread"] and not x["proposed_same_thread"]:
                print("MERGE-ONLY", x["left"], x["right"], x["gap_hours"], x["overlap"], x["left_last_kind"], x["why"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
