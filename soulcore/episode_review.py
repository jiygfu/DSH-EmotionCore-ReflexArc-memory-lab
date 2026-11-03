#!/usr/bin/env python3
"""Local 2B event-closure review.

This is a maintenance worker, not a chat tool. It reviews open episodes and
asks the local small model whether the event has naturally ended / its issue is
resolved. Only high-confidence closed=True changes the episode status.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from . import appraise, db

PROMPT = """你是本地记忆整理器，不是对话角色。
判断下面这段聊天事件现在是否已经自然结束，或者其中的问题/请求已经解决。

只输出 JSON：
{{"closed": true/false, "confidence": 0.0-1.0, "reason": "一句中文理由"}}

判断规则：
- 只有明确收尾、问题已答复、请求已完成、双方自然结束时才 closed=true；
- 时间过去很久、只是没人说话，不等于已解决；
- 仍有未答问题、未完成请求、未解决冲突时 closed=false；
- 不确定就 closed=false，confidence 相应降低；
- 不要复述原文，不要编造事件里没有的信息。

事件日期：{day}
摘要：{summary}
关键引语：{quote}
感受：{felt}
未解决度：{unresolved}
"""


def _review_prompt(row: sqlite3.Row) -> str:
    return PROMPT.format(
        day=row["day"] or "",
        summary=str(row["summary"] or "")[:600],
        quote=str(row["key_quote"] or "")[:400],
        felt=str(row["felt"] or "")[:300],
        unresolved=float(row["unresolved"] or 0),
    )


def _parse(raw: str) -> dict[str, Any]:
    data = json.loads(appraise._strip_json(raw))
    return {
        "closed": bool(data.get("closed")),
        "confidence": max(0.0, min(1.0, float(data.get("confidence") or 0.0))),
        "reason": str(data.get("reason") or "")[:300],
    }


ENDING_RE = re.compile(r"(晚安|拜拜|再见|886|先这样|先这么着|先撤|溜了|去忙|下了|睡了|不聊了|回头聊|改天聊|明天聊|下次聊|到此为止)")
QUESTION_RE = re.compile(r"([?？]\s*$|(吗|嘛|么|咋|怎么|为什么|为啥|什么|哪个|哪里|哪儿|谁|多少|几点|是不是|有没有|能不能|可不可以|要不要|好不好|对不对|行不行)\s*[。！!…～~]*$)")
REQUEST_RE = re.compile(r"(帮我|帮忙|麻烦你|请你|教我|告诉我|说说|讲讲|发我|给我|推荐|查一下|搜一下|找一下|看一下|写一个|弄一个|来个|整一个)")
SETTLED_RE = re.compile(r"(说好了|就这么定|扯平|一言为定|成交|定了|好啦|行啦|算啦|先这样|以后再说|下次再说|不说了|不提了|到此为止|翻篇)")


def _closing_signals(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> dict[str, Any]:
    ids: list[str] = []
    for row in rows:
        try:
            ids.extend(str(x) for x in json.loads(row["raw_ids_json"] or "[]"))
        except Exception:
            pass
    last = None
    if ids:
        marks = ",".join("?" for _ in ids)
        last = conn.execute(
            f"SELECT text, ts, speaker FROM memories WHERE id IN ({marks}) ORDER BY COALESCE(ts,created_at) DESC LIMIT 1",
            tuple(ids),
        ).fetchone()
    text = str(last["text"] if last else "")[:500]
    kind = "substantive"
    if not text:
        kind = "silence"
    elif ENDING_RE.search(text) and len(text) <= 30:
        kind = "ending"
    elif QUESTION_RE.search(text):
        kind = "question"
    elif REQUEST_RE.search(text):
        kind = "request"
    elif SETTLED_RE.search(text):
        kind = "settled"
    return {
        "last_text": text,
        "last_kind": kind,
        "has_question": kind == "question",
        "has_request": kind == "request",
        "has_ending": kind == "ending",
        "settled": kind == "settled",
        "speaker": str(last["speaker"] or "") if last else "",
    }


def _thread_prompt(rows: list[sqlite3.Row], signals: dict[str, Any] | None = None) -> str:
    signals = signals or {}
    parts = []
    for i, row in enumerate(rows[:5], 1):
        parts.append(
            f"[片段{i}] {row['day'] or ''} 未解决度={float(row['unresolved'] or 0):.2f}\n"
            f"摘要：{str(row['summary'] or '')[:420]}\n"
            f"引语：{str(row['key_quote'] or '')[:220]}\n"
            f"感受：{str(row['felt'] or '')[:160]}"
        )
    return """你是本地记忆整理器，不是对话角色。
下面是一个可能跨天延续的“事件线程”的多个片段。判断整件事现在是否已经自然结束，或者其中的问题/请求已经解决。

只输出 JSON：
{{"closed": true/false, "confidence": 0.0-1.0, "reason": "一句中文理由"}}

判断规则：
- 只有整件事明确收尾、问题已答复、请求已完成、双方自然结束时才 closed=true；
- 只是某个片段结束、隔了一段时间、或某天没人说话，不代表整个线程结束；
- 仍有未答问题、未完成请求、未解决冲突时 closed=false；
- 不确定就 closed=false，confidence 相应降低；
- 不要复述原文，不要编造片段里没有的信息。

程序收尾信号（只做参考，不是结论）：
最后一条消息类型：{last_kind}
最后一条消息：{last_text}
有未答问题：{has_question}
有未完成请求：{has_request}
有明确道别：{has_ending}
有收束语气：{settled}

以下是同一线程的片段：
{segments}
""".format(segments="\n\n".join(parts), last_kind=signals.get("last_kind","unknown"), last_text=signals.get("last_text",""), has_question=signals.get("has_question",False), has_request=signals.get("has_request",False), has_ending=signals.get("has_ending",False), settled=signals.get("settled",False))


def review_open(conn: sqlite3.Connection, *, limit: int = 2, timeout: int = 180, force: bool = False) -> dict[str, int]:
    cutoff = (datetime.now().astimezone() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        """SELECT * FROM episodes
           WHERE status='open'
           ORDER BY COALESCE(thread_id,id), COALESCE(start_at, created_at) ASC"""
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(str(row["thread_id"] or row["id"]), []).append(row)
    candidates = []
    for tid, items in groups.items():
        if force or any((not r["reviewed_at"]) or str(r["reviewed_at"]) < cutoff for r in items):
            candidates.append((tid, items))
    candidates.sort(key=lambda x: str(x[1][0]["start_at"] or x[1][0]["created_at"] or ""))

    cfg = appraise.appraiser_config()
    model = str(cfg.get("model") or db.MODEL)
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:11434")
    stats = {"reviewed": 0, "closed": 0, "kept": 0, "failed": 0, "threads": 0}
    for tid, items in candidates[: max(1, min(20, int(limit)))]:
        now = datetime.now().astimezone().isoformat()
        try:
            body = {
                "model": model,
                "prompt": _thread_prompt(items, _closing_signals(conn, items)),
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 180},
            }
            data = appraise._post_json("/api/generate", body, timeout=timeout, base_url=base_url)
            result = _parse(str(data.get("response") or ""))
            stats["threads"] += 1
            stats["reviewed"] += len(items)
            if result["closed"] and result["confidence"] >= 0.72:
                conn.execute(
                    """UPDATE episodes
                       SET status='closed', closed_at=?, resolution_note=?,
                           closure_confidence=?, closure_source='local-2b-thread', reviewed_at=?
                       WHERE thread_id=?""",
                    (now, result["reason"], result["confidence"], now, tid),
                )
                stats["closed"] += len(items)
            else:
                conn.execute(
                    """UPDATE episodes
                       SET closure_confidence=?, closure_source='local-2b-thread', reviewed_at=?
                       WHERE thread_id=?""",
                    (result["confidence"], now, tid),
                )
                stats["kept"] += len(items)
            conn.commit()
        except Exception:
            stats["failed"] += 1
            conn.rollback()
    return stats
