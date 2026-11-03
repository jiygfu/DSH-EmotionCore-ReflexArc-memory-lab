#!/usr/bin/env python3
"""Open loops for event threads.

Pure local rules. A loop is a *thread-level* state derived from the last real
message, not a separate memory and not a hard close decision.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any

ENDING_RE = re.compile(r"(晚安|拜拜|再见|886|先这样|先这么着|先撤|溜了|去忙|下了|睡了|不聊了|回头聊|改天聊|明天聊|下次聊|到此为止)")
QUESTION_RE = re.compile(r"([?？]\s*$|(吗|嘛|么|咋|怎么|为什么|为啥|什么|哪个|哪里|哪儿|谁|多少|几点|是不是|有没有|能不能|可不可以|要不要|好不好|对不对|行不行)\s*[。！!…～~]*$)")
REQUEST_RE = re.compile(r"(帮我|帮忙|麻烦你|请你|教我|告诉我|说说|讲讲|发我|给我|推荐|查一下|搜一下|找一下|看一下|写一个|弄一个|来个|整一个)")
SETTLED_RE = re.compile(r"(说好了|就这么定|扯平|一言为定|成交|定了|好啦|行啦|算啦|先这样|以后再说|下次再说|不说了|不提了|到此为止|翻篇)")
ANCHOR_RE = re.compile(r"(明天|后天|今晚|周末|下周[一二三四五六日天]|回头|改天|下次|晚点|等会|稍后|半小时后|(\d+|[一二两三四五六七八九十]+)(分钟|小时)后)")


def _clip(text: str, n: int = 80) -> str:
    return " ".join(str(text or "").split())[:n]


def classify(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return "silence"
    if ENDING_RE.search(t) and len(t) <= 30:
        return "ending"
    if QUESTION_RE.search(t):
        return "question"
    if REQUEST_RE.search(t):
        return "request"
    if ANCHOR_RE.search(t):
        return "anchor"
    if SETTLED_RE.search(t):
        return "settled"
    return "substantive"


def _parse_anchor(text: str, now: datetime) -> tuple[str, str | None]:
    t = str(text or "")
    m = re.search(r"(明天|后天|今晚|周末|下周[一二三四五六日天]|回头|改天|下次|晚点|等会|稍后|半小时后)", t)
    if not m:
        m2 = re.search(r"(\d+|[一二两三四五六七八九十]+)\s*(分钟|小时)(?:后|以后|之后)", t)
        if not m2:
            return "", None
        num = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}.get(m2.group(1), None)
        n = int(m2.group(1)) if str(m2.group(1)).isdigit() else (num if num is not None else 0)
        if n <= 0:
            return "", None
        delta = timedelta(minutes=n) if m2.group(2) == "分钟" else timedelta(hours=n)
        return m2.group(0), (now + delta).isoformat()
    word = m.group(0)
    if word == "明天":
        at = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    elif word == "后天":
        at = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    elif word == "今晚":
        at = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
    elif word.startswith("下周"):
        at = now + timedelta(days=7)
    elif word == "周末":
        at = now + timedelta(days=max(1, 5 - now.weekday()))
    else:
        return word, None
    return word, at.isoformat()


def _last_memory(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> sqlite3.Row | None:
    ids: list[str] = []
    for row in rows:
        try:
            ids.extend(str(x) for x in json.loads(row["raw_ids_json"] or "[]"))
        except Exception:
            pass
    if not ids:
        return None
    marks = ",".join("?" for _ in ids)
    return conn.execute(
        f"SELECT id,text,ts,speaker FROM memories WHERE id IN ({marks}) ORDER BY COALESCE(ts,created_at) DESC LIMIT 1",
        tuple(ids),
    ).fetchone()


def sync_thread_loops(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS thread_loops (
          thread_id TEXT PRIMARY KEY,
          status TEXT NOT NULL,
          kind TEXT NOT NULL,
          one_line TEXT,
          anchor_text TEXT,
          anchor_at TEXT,
          evidence_json TEXT,
          updated_at TEXT NOT NULL
        )"""
    )
    rows = conn.execute(
        "SELECT * FROM episodes WHERE status='open' ORDER BY COALESCE(thread_id,id), COALESCE(start_at,created_at) ASC"
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(str(row["thread_id"] or row["id"]), []).append(row)
    now = datetime.now().astimezone()
    stats = {"threads": 0, "waiting": 0, "paused": 0, "closing": 0, "open": 0}
    for tid, items in groups.items():
        last = _last_memory(conn, items)
        text = str(last["text"] if last else items[-1]["summary"] or "")
        kind = classify(text)
        status = "open"
        if kind == "ending":
            status = "closing"
        elif kind in ("question", "request"):
            status = "waiting"
        elif kind == "anchor":
            status = "paused"
        elif kind == "settled":
            status = "closing"
        anchor_text, anchor_at = _parse_anchor(text, now) if kind == "anchor" else ("", None)
        one_line = _clip(text, 60) or _clip(str(items[-1]["summary"] or ""), 60)
        conn.execute(
            """INSERT INTO thread_loops
               (thread_id,status,kind,one_line,anchor_text,anchor_at,evidence_json,updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(thread_id) DO UPDATE SET
                 status=excluded.status, kind=excluded.kind, one_line=excluded.one_line,
                 anchor_text=excluded.anchor_text, anchor_at=excluded.anchor_at,
                 evidence_json=excluded.evidence_json, updated_at=excluded.updated_at""",
            (tid, status, kind, one_line, anchor_text, anchor_at,
             json.dumps([last["id"]] if last else [], ensure_ascii=False), now.isoformat()),
        )
        stats["threads"] += 1
        if status in stats:
            stats[status] += 1
    active = set(groups.keys())
    if active:
        marks = ",".join("?" for _ in active)
        conn.execute(f"DELETE FROM thread_loops WHERE thread_id NOT IN ({marks})", tuple(active))
    conn.commit()
    return stats


def open_loops(conn: sqlite3.Connection, *, limit: int = 2) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT * FROM thread_loops WHERE status IN ('waiting','paused','closing') ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(10, int(limit))),),
        ).fetchall()
    except Exception:
        return []
    return [dict(r) for r in rows]
