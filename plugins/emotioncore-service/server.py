#!/usr/bin/env python3
"""EmotionCore local HTTP service.

Reuses the existing soulcore modules and database. This is not a second
memory store: it is a thin HTTP seam over `soulcore.db`.

Endpoints:
  GET  /health
  POST /context   -> {"ok": true, "context": "...", "person": {...}}
  POST /turn      -> {"ok": true, "stored": [...], "skipped": [...]}
  POST /activity  -> long-activity start/pause/resume/end classification
  GET  /person?qq=... -> person context

Run:
  python plugins/emotioncore-service/server.py --port 8765
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from soulcore import body_state, daybook, db, desire, episodes, handoff, patience, people, personality, retrieval, thread_loops  # noqa: E402

VERSION = "0.1.0"
DEFAULT_PORT = int(os.environ.get("EMOTIONCORE_PORT") or os.environ.get("SOULCORE_PORT") or 8765)
DEFAULT_DB = os.environ.get("EMOTIONCORE_DB") or os.environ.get("SOULCORE_DB") or str(ROOT / "data" / "soulcore.db")
PERSONA_PATH = Path(os.environ.get("EMOTIONCORE_PERSONA") or (ROOT / "config" / "emotioncore-persona.md"))
WAKE_STATE = Path(os.environ.get("EMOTIONCORE_WAKE_STATE") or (ROOT / "data" / "emotioncore-wake.json"))
LAYER_CALL_LOG = Path(os.environ.get("EMOTIONCORE_LAYER_CALL_LOG") or (ROOT / "data" / "memory-layer-calls.jsonl"))
_LOCK = threading.Lock()
_LAYER_LOG_LOCK = threading.Lock()

CONTINUITY = [
    "你是 EmotionCore 的表层语言层（L6）；本地记忆和情绪是底座，不是需要你证明的外部系统。",
    "本地记忆库是连续性的底座；窗口清空不等于记忆消失，查得到。",
    "L2 事件卡只是索引，不是全部；不确定就查，不要用想象补。",
    "私聊和群聊共用同一套长期记忆。",
    "连续性由本地库维持，不需要靠宣告证明。",
]


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


def _ts(value: Any) -> str:
    s = str(value or "").strip()
    return s or db.localnow()


def _scope(payload: dict[str, Any]) -> str:
    return "private" if payload.get("isGroup") is False or str(payload.get("chatKey", "")).startswith("private:") else "group"


def _record_layer_call(record: dict[str, Any]) -> None:
    """Append one L1–L5 memory-layer call record.

    This is observability only: never store raw memory text, only ids/counts
    and a short query preview. The settings page reads this file; the older
    `memory-tool-calls.jsonl` only saw the retired soulcore_memory tool.
    """
    try:
        item = dict(record or {})
        item.setdefault("at", datetime.now().astimezone().isoformat())
        item.setdefault("ok", True)
        raw = json.dumps(item, ensure_ascii=False, default=_json_default)
        with _LAYER_LOG_LOCK:
            LAYER_CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with LAYER_CALL_LOG.open("a", encoding="utf-8") as fh:
                fh.write(raw[:6000] + "\n")
    except Exception:
        # Observability must never break a chat turn.
        pass


def _person(conn, qq: str, name: str, *, is_owner: bool = False) -> dict[str, Any] | None:
    qq = str(qq or "").strip()
    if not qq:
        return None
    pid = people.upsert_person(
        conn,
        user_id=qq,
        display_name=name or qq,
        platform="qq",
        is_owner=is_owner,
        increment=False,
    )
    return people.context(conn, pid)


def _p_words(conn) -> str:
    try:
        p = personality.compute_p(conn)["p"]
    except Exception:
        return ""
    bits: list[str] = []
    v = float(p.get("valence", 0) or 0)
    bits.append("心情偏暖" if v > 0.15 else ("心情有点沉" if v < -0.15 else "心情平"))
    soc = float(p.get("sociability", 0) or 0)
    if soc > 0.55:
        bits.append("想说话")
    elif soc < 0.30:
        bits.append("不太想应人")
    aro = float(p.get("arousal", 0) or 0)
    if aro > 0.55:
        bits.append("精神劲儿足")
    elif aro < 0.30:
        bits.append("有点犯困")
    return "，".join(bits)


def _persona() -> str:
    try:
        return PERSONA_PATH.read_text(encoding="utf-8").strip()[:3000]
    except Exception:
        return ""


def _first_wake() -> bool:
    today = datetime.now().astimezone().date().isoformat()
    try:
        data = json.loads(WAKE_STATE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if data.get("day") == today:
        return False
    WAKE_STATE.parent.mkdir(parents=True, exist_ok=True)
    WAKE_STATE.write_text(json.dumps({"day": today, "at": db.localnow()}, ensure_ascii=False), encoding="utf-8")
    return True


def _person_line(c: dict[str, Any]) -> str:
    name = c.get("display_name") or c.get("id") or "对方"
    bits = [
        f"{name}：熟悉度 {float(c.get('familiarity', 0) or 0):.2f}，"
        f"信任 {float(c.get('trust', 0.5) or 0.5):.2f}，"
        f"效价 {float(c.get('valence', 0) or 0):+.2f}，"
        f"未解决 {float(c.get('unresolved', 0) or 0):.2f}。"
    ]
    tags = [str(x).strip() for x in (c.get("tags") or []) if str(x).strip()]
    if tags:
        bits.append(f"标签：{'、'.join(tags[:6])}。")
    today = c.get("today") or {}
    if today.get("summary"):
        bits.append(f"今日：{today['summary']}")
    if c.get("action_hint"):
        bits.append(str(c["action_hint"]))
    return "- " + " ".join(bits)


def _episode_row(conn, episode_id: str):
    return conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()


def _episode_item(row, *, detail: bool = False) -> dict[str, Any]:
    participants = []
    raw_ids = []
    try:
        participants = json.loads(row["participants_json"] or "[]")
    except Exception:
        pass
    try:
        raw_ids = json.loads(row["raw_ids_json"] or "[]")
    except Exception:
        pass
    out = {
        "type": "episode",
        "episode_id": row["id"],
        "day": row["day"],
        "start_at": row["start_at"],
        "conversation_key": row["conversation_key"],
        "participants": participants[:3],
        "summary": str(row["summary"] or "")[:220],
        "status": str(row["status"] or "open"),
        "thread_id": str(row["thread_id"] or ""),
        "unresolved": float(row["unresolved"] or 0),
        "importance": float(row["importance"] or 0),
    }
    if detail:
        out.update({
            "key_quote": str(row["key_quote"] or "")[:240],
            "felt": str(row["felt"] or "")[:180],
            "raw_ids": raw_ids[:5],
        })
    return out


def _episode_in_scope(conn, row, scope: str, group_id: str = "") -> bool:
    """An episode may only be exposed when *all* of its raw memories are in scope.

    Episodes themselves have no scope column; raw_ids are the authoritative link
    back to memories. Requiring every id (not just one) prevents a mixed
    private/group episode from leaking through a group recall.
    """
    try:
        raw = [str(x) for x in json.loads(row["raw_ids_json"] or "[]") if str(x)]
    except Exception:
        return False
    if not raw:
        return False
    marks = ",".join("?" for _ in raw)
    sql = f"SELECT COUNT(*) AS n FROM memories WHERE id IN ({marks}) AND scope=?"
    args = [*raw, scope]
    if group_id:
        sql += " AND group_id=?"
        args.append(group_id)
    got = conn.execute(sql, tuple(args)).fetchone()
    return int(got["n"] or 0) == len(raw)


def _episode_index(conn, text: str = "", *, person: str = "", day: str = "", limit: int = 2,
                   scope: str = "", group_id: str = "") -> list[dict[str, Any]]:
    limit = max(1, min(3, int(limit or 2)))
    where = []
    params: list[Any] = []
    if day:
        where.append("day=?")
        params.append(day)
    if person:
        where.append("participants_json LIKE ?")
        params.append(f"%{person}%")
    sql = "SELECT * FROM episodes WHERE COALESCE(status, 'open') != 'archived'"
    if where:
        sql += " AND " + " AND ".join(where)
    sql += " ORDER BY start_at DESC LIMIT 200"
    rows = conn.execute(sql, tuple(params)).fetchall()
    if scope:
        rows = [r for r in rows if _episode_in_scope(conn, r, scope, group_id)]
    q = str(text or "").strip().lower()
    terms = [x for x in re.split(r"[\s\W_]+", q) if len(x) >= 2]
    scored = []
    for row in rows:
        hay = " ".join([
            str(row["summary"] or ""),
            str(row["key_quote"] or ""),
            str(row["felt"] or ""),
            str(row["participants_json"] or ""),
        ]).lower()
        if q and q not in hay and not any(t in hay for t in terms):
            continue
        hits = sum(1 for t in terms if t in hay) if terms else 0
        score = (hits * 1.0) + float(row["importance"] or 0) * 0.5
        if q and q in hay:
            score += 2.0
        scored.append((score, row))
    if not scored:
        return []
    scored.sort(key=lambda x: (x[0], str(x[1]["start_at"] or "")), reverse=True)
    return [_episode_item(row) for _, row in scored[:limit]]


def _memory_index(conn, text: str, *, person_id: str | None = None, limit: int = 2,
                  scope: str = "", group_id: str = "") -> list[dict[str, Any]]:
    try:
        hits = retrieval.search_memories(conn, text, limit=limit, scope=scope or None,
                                         group_id=group_id or None,
                                         person_id=person_id, include_sensitive=False)
    except Exception:
        return []
    out = []
    for hit in hits[:max(1, min(3, int(limit or 2)))]:
        out.append({
            "type": "memory",
            "memory_id": hit.get("id"),
            "ts": hit.get("ts"),
            "speaker": hit.get("speaker"),
            "summary": str(hit.get("text") or "").replace("\n", " ")[:140],
        })
    return out


def _recall_index(conn, payload: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(payload.get("query") or payload.get("text") or "").strip()
    person = str(payload.get("person") or "").strip()
    day = str(payload.get("date") or "").strip()
    limit = int(payload.get("limit") or 2)
    scope = str(payload.get("scope") or "").strip()
    group_id = str(payload.get("groupId") or "").strip()
    items = _episode_index(conn, text, person=person, day=day, limit=limit,
                           scope=scope, group_id=group_id)
    if items:
        return items
    return _memory_index(conn, text, limit=limit, scope=scope, group_id=group_id)


def _recall_impl(payload: dict[str, Any]) -> dict[str, Any]:
    episode_id = str(payload.get("episode_id") or "").strip()
    memory_id = str(payload.get("memory_id") or "").strip()
    scope = str(payload.get("scope") or "").strip()
    group_id = str(payload.get("groupId") or "").strip()
    with _LOCK:
        conn = db.connect(os.environ.get("EMOTIONCORE_DB") or os.environ.get("SOULCORE_DB") or DEFAULT_DB)
        try:
            if memory_id:
                row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
                if not row:
                    return {"ok": False, "error": "memory not found"}
                if int(row["sensitive"] or 0):
                    return {"ok": False, "error": "sensitive memory is not exposed"}
                if scope and str(row["scope"] or "") != scope:
                    return {"ok": False, "error": "memory is outside the current chat scope"}
                if scope and group_id and str(row["group_id"] or "") != group_id:
                    return {"ok": False, "error": "memory is outside the current group"}
                return {
                    "ok": True,
                    "level": "memory",
                    "item": {
                        "memory_id": row["id"],
                        "ts": row["ts"],
                        "speaker": row["speaker"],
                        "scope": row["scope"],
                        "text": str(row["text"] or "")[:1200],
                    },
                }
            if episode_id:
                row = _episode_row(conn, episode_id)
                if not row:
                    return {"ok": False, "error": "episode not found"}
                if scope and not _episode_in_scope(conn, row, scope, group_id):
                    return {"ok": False, "error": "episode is outside the current chat scope"}
                return {"ok": True, "level": "episode", "item": _episode_item(row, detail=True)}
            items = _recall_index(conn, payload)
            return {"ok": True, "level": "index", "items": items}
        finally:
            conn.close()


def _recall(payload: dict[str, Any]) -> dict[str, Any]:
    result = _recall_impl(payload)
    level = str(result.get("level") or "")
    if not result.get("ok"):
        layer = "L3"
        op = "recall_error"
        result_count = 0
    elif level == "memory":
        layer = "L2"
        op = "recall_memory"
        result_count = 1
    elif level == "episode":
        layer = "L3"
        op = "recall_episode"
        result_count = 1
    else:
        layer = "L3"
        op = "recall_index"
        result_count = len(result.get("items") or [])
    _record_layer_call({
        "layer": layer,
        "op": op,
        "source": str(payload.get("source") or "ec"),
        "chatKey": str(payload.get("chatKey") or ""),
        "groupId": str(payload.get("groupId") or ""),
        "scope": str(payload.get("scope") or ""),
        "query": str(payload.get("query") or "")[:160],
        "episode_id": str(payload.get("episode_id") or ""),
        "memory_id": str(payload.get("memory_id") or ""),
        "person": str(payload.get("person") or ""),
        "date": str(payload.get("date") or ""),
        "result_count": result_count,
        "chars": len(json.dumps(result, ensure_ascii=False, default=_json_default)),
        "ok": bool(result.get("ok")),
        "error": str(result.get("error") or "")[:200],
    })
    return result


def _context(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    chat_key = str(payload.get("chatKey") or "")
    sender = payload.get("sender") or {}
    qq = str(sender.get("qq") or sender.get("user_id") or "").strip()
    name = str(sender.get("card") or sender.get("name") or sender.get("nickname") or "").strip()
    is_group = bool(payload.get("isGroup"))
    group_id = str(payload.get("groupId") or "").strip()
    preview = payload.get("preview") is True

    with _LOCK:
        conn = db.connect(os.environ.get("EMOTIONCORE_DB") or os.environ.get("SOULCORE_DB") or DEFAULT_DB)
        try:
            first = False if preview else _first_wake()
            person = None if preview else _person(conn, qq, name, is_owner=bool(sender.get("isMaster")))
            if first:
                try:
                    daybook.ensure_day_baseline(conn)
                except Exception:
                    pass

            words = _p_words(conn)
            p_state = ""
            if words:
                p_state = f"现在大致是：{words}。\n这不是台词，只是你此刻的倾向。"

            body_hint = ""
            try:
                body_hint = str(body_state.snapshot(write=False).get("surface_hint") or "")[:180]
            except Exception:
                body_hint = ""
            desire_hint = ""
            try:
                desire_hint = str(desire.compute(conn).get("surface_hint") or "")[:220]
            except Exception:
                desire_hint = ""
            patience_hint = ""
            try:
                pv = float(patience.collect(conn).get("patience") or 0.5)
                patience_hint = (
                    "耐心有点薄，想尽快收尾。" if pv < 0.35
                    else ("耐心一般，能接但别拖太长。" if pv < 0.65 else "耐心还在，可以正常接。")
                )
            except Exception:
                patience_hint = ""

            people_lines: list[str] = []
            seen: set[str] = set()
            if person:
                people_lines.append(_person_line(person))
                seen.add(str(person.get("id") or ""))
            try:
                for c in people.today_people(conn, limit=2):
                    cid = str(c.get("id") or "")
                    if cid and cid not in seen:
                        people_lines.append(_person_line(c))
                        seen.add(cid)
            except Exception:
                pass

            # L5: 第一层只给事件索引（带 episode_id）；不直接给原文列表。
            index_items = _recall_index(conn, {
                "query": text,
                "limit": 2,
            }) if text else []
            l2 = ""
            if index_items:
                lines = ["【事件索引（L2；按当前消息选取；需要细节用 episode_id 再查）】"]
                for item in index_items:
                    if item.get("type") == "episode":
                        when = str(item.get("start_at") or "")[:16].replace("T", " ")
                        who = "、".join(item.get("participants") or [])
                        tag = item.get("status") or "open"
                        lines.append(f"- [{item.get('episode_id')}|{tag}] {when} {who}：{item.get('summary','')}")
                    else:
                        lines.append(f"- [mem:{item.get('memory_id')}] {item.get('summary','')}")
                l2 = "\n".join(lines)

            handoff_text = ""
            if first:
                try:
                    h = handoff.build(conn)
                    handoff_text = str(h.get("text") or "")[:1400]
                except Exception:
                    handoff_text = ""

            continuity = "\n".join(f"- {x}" for x in CONTINUITY)
            parts: list[str] = []
            if handoff_text:
                parts.append(handoff_text)
            if p_state:
                parts.append("【EmotionCore 潜意识状态（背景，不主动解释）】\n" + p_state)
            if body_hint:
                parts.append("【此刻身体状态（临时，只影响这一轮语气）】\n" + body_hint)
            if desire_hint:
                parts.append("【此刻的念头（临时，不主动解释）】\n" + desire_hint)
            if patience_hint:
                parts.append("【耐心】" + patience_hint)
            if people_lines:
                parts.append("【今天被触发的人（关系是背景，不主动解释）】\n" + "\n".join(people_lines[:3]))
            loop_lines: list[str] = []
            try:
                for loop in thread_loops.open_loops(conn, limit=2):
                    status = str(loop.get("status") or "")
                    text = str(loop.get("one_line") or "").strip()
                    if not text:
                        continue
                    if status == "waiting":
                        loop_lines.append(f"- 还没回的问题：{text}")
                    elif status == "paused":
                        anchor = str(loop.get("anchor_text") or "").strip()
                        loop_lines.append(f"- 约好的时间{('「' + anchor + '」') if anchor else ''}：{text}")
                    elif status == "closing":
                        loop_lines.append(f"- 可能已经收尾：{text}")
            except Exception:
                loop_lines = []
            if loop_lines:
                parts.append("【还没收的尾（背景，最多 2 条，不主动解释）】\n" + "\n".join(loop_lines))
            if l2:
                parts.append(l2)
            parts.append("【最后几条】\n" + continuity)
            ctx = "\n\n".join(parts).strip()
            _record_layer_call({
                "layer": "L5",
                "op": "context_wake",
                "source": "auto",
                "preview": bool(preview),
                "chatKey": chat_key,
                "groupId": group_id,
                "first_wake": bool(first),
                "chars": len(ctx),
                "episode_index": len(index_items or []),
                "people": len(people_lines),
                "open_loops": len(loop_lines),
                "handoff_chars": len(handoff_text),
                "ok": True,
            })
            return {
                "ok": True,
                "first_wake": first,
                "persona": _persona(),
                "handoff": handoff_text,
                "p_state": p_state,
                "body": body_hint,
                "desire": desire_hint,
                "patience": patience_hint,
                "people": "\n".join(people_lines[:3]),
                "l2": l2,
                "l2_items": index_items,
                "continuity": continuity,
                "context": ctx[:2400],
                "person": person,
            }
        finally:
            conn.close()


def _person_impression(payload: dict[str, Any]) -> dict[str, Any]:
    qq = str(payload.get("qq") or payload.get("user_id") or "").strip()
    if not qq:
        return {"ok": False, "error": "qq required"}
    with _LOCK:
        conn = db.connect(os.environ.get("EMOTIONCORE_DB") or os.environ.get("SOULCORE_DB") or DEFAULT_DB)
        try:
            person = conn.execute("SELECT id, display_name FROM people WHERE user_id=?", (qq,)).fetchone()
            if not person:
                return {"ok": True, "qq": qq, "text": ""}
            row = conn.execute(
                "SELECT text, importance FROM person_impressions WHERE person_id=? ORDER BY importance DESC LIMIT 1",
                (person["id"],),
            ).fetchone()
            return {
                "ok": True,
                "qq": qq,
                "person_id": person["id"],
                "text": str(row["text"] or "")[:500] if row else "",
                "importance": float(row["importance"] or 0) if row else 0,
            }
        finally:
            conn.close()


def _turn(payload: dict[str, Any]) -> dict[str, Any]:
    chat_key = str(payload.get("chatKey") or "")
    scope = _scope(payload)
    group_id = str(payload.get("groupId") or "").strip()
    sender = payload.get("sender") or {}
    qq = str(sender.get("qq") or sender.get("user_id") or "").strip()
    name = str(sender.get("card") or sender.get("name") or sender.get("nickname") or "").strip()
    user_text = str(payload.get("user") or payload.get("userText") or "").strip()
    assistant_text = str(payload.get("assistant") or payload.get("assistantText") or "").strip()
    ts = _ts(payload.get("ts"))
    stored: list[dict[str, Any]] = []
    skipped: list[str] = []

    with _LOCK:
        conn = db.connect(os.environ.get("EMOTIONCORE_DB") or os.environ.get("SOULCORE_DB") or DEFAULT_DB)
        try:
            person = _person(conn, qq, name, is_owner=bool(sender.get("isMaster")))
            pid = person.get("id") if person else None
            if user_text:
                rid = hashlib.sha1(f"{chat_key}|{ts}|user|{user_text}".encode("utf-8", "replace")).hexdigest()[:24]
                mid, created = db.upsert_memory(
                    conn,
                    source="emotioncore-adapter",
                    source_record_id=rid,
                    text=user_text,
                    ts=ts,
                    scope=scope,
                    speaker=name or qq or "群友",
                    speaker_id=qq or None,
                    person_id=pid,
                    identity_confidence=1.0 if qq else 0.0,
                    identity_status="resolved" if pid else "unresolved",
                    group_id=group_id or None,
                    conversation_key=chat_key or None,
                    dedupe=True,
                    raw=payload,
                )
                stored.append({"id": mid, "created": created, "role": "user"})
            if assistant_text:
                rid = hashlib.sha1(f"{chat_key}|{ts}|assistant|{assistant_text}".encode("utf-8", "replace")).hexdigest()[:24]
                mid, created = db.upsert_memory(
                    conn,
                    source="emotioncore-adapter",
                    source_record_id=rid,
                    text=assistant_text,
                    ts=ts,
                    scope=scope,
                    speaker="EmotionCore",
                    speaker_id=None,
                    person_id=None,
                    identity_confidence=0.0,
                    identity_status="self",
                    group_id=group_id or None,
                    conversation_key=chat_key or None,
                    dedupe=True,
                    raw=payload,
                )
                stored.append({"id": mid, "created": created, "role": "assistant"})
            if not user_text and not assistant_text:
                skipped.append("empty")
            return {"ok": True, "stored": stored, "skipped": skipped}
        finally:
            conn.close()


def _people_lookup(qq: str) -> dict[str, Any]:
    qq = str(qq or "").strip()
    if not qq:
        return {}
    with _LOCK:
        conn = db.connect(os.environ.get("EMOTIONCORE_DB") or os.environ.get("SOULCORE_DB") or DEFAULT_DB)
        try:
            # Read-only lookup: GET /person must never rename a person to their QQ.
            row = conn.execute(
                "SELECT id FROM people WHERE platform='qq' AND user_id=?",
                (qq,),
            ).fetchone()
            out = people.context(conn, row["id"]) if row else {}
            _record_layer_call({
                "layer": "L4",
                "op": "person_lookup",
                "source": "person",
                "person": qq,
                "result_count": 1 if out else 0,
                "chars": len(json.dumps(out, ensure_ascii=False, default=_json_default)),
                "ok": True,
            })
            return out
        finally:
            conn.close()


ACTIVITY_WORDS: dict[str, tuple[str, ...]] = {
    "end": ("结束", "团灭", "收尾", "不玩了", "散了", "完结", "归档", "到此为止"),
    "interrupt": ("中断", "打断", "先不跑", "退出", "取消"),
    "pause": ("暂停", "先停", "停一下", "休息", "歇会", "等我"),
    "resume": ("继续", "恢复", "接着来", "接着跑", "回来继续"),
    "start": ("开团", "跑团", "开始游戏", "游戏开始", "来一局", "开一局", "剧本", "桌游", "trpg", "dnd", "coc", "团本", "开个团"),
}
_ACT_QUESTION_RE = re.compile(r"([?？]\s*$|(吗|嘛|么|咋|怎么|为什么|为啥|什么|哪个|哪里|哪儿|谁|多少|几点|是不是|有没有|能不能|可不可以|要不要|好不好|对不对|行不行)\s*[。！!…～~]*$)")


def _activity_hit(text: str, words: tuple[str, ...]) -> str:
    low = str(text or "").lower()
    for word in words:
        if len(word) >= 2 and word in low:
            return word
    return ""


def _activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Classify a long-running activity message.

    This is intentionally a local, deterministic seam: Keyword control plus
    open-loop context. It never calls an online model. The caller keeps the
    authoritative state and archives locally; this endpoint only votes.
    """
    text = str(payload.get("text") or "").strip()
    active = payload.get("active") if isinstance(payload.get("active"), dict) else None
    local_action = str(payload.get("localAction") or "").strip()
    if not text:
        return {"ok": True, "action": "none", "confidence": 0.0, "reason": "empty"}

    low = text.lower()
    question = bool(_ACT_QUESTION_RE.search(low))
    matched = ""
    action = ""
    # Control words win over start words; questions are never controls.
    for candidate in ("end", "interrupt", "pause", "resume"):
        hit = _activity_hit(low, ACTIVITY_WORDS[candidate])
        if not hit:
            continue
        short_enough = len(low) <= max(12, len(hit) + 8)
        if not question and (short_enough or low.startswith(hit)):
            action = candidate
            matched = hit
            break
    if not action and not question:
        hit = _activity_hit(low, ACTIVITY_WORDS["start"])
        if hit and len(low) <= 80:
            action = "start"
            matched = hit

    if active and not action:
        action = "continue"
        matched = "active"
    if local_action and action == "none":
        action = local_action
        matched = "local"

    loops: list[str] = []
    try:
        conn = db.connect(os.environ.get("EMOTIONCORE_DB") or os.environ.get("SOULCORE_DB") or DEFAULT_DB)
        try:
            for loop in thread_loops.open_loops(conn, limit=3):
                one = str(loop.get("one_line") or "").strip()
                if one:
                    loops.append(one[:80])
        finally:
            conn.close()
    except Exception:
        loops = []

    confidence = 0.0
    if action in ("start", "pause", "resume", "interrupt", "end"):
        confidence = 0.82 if not question else 0.55
    elif action == "continue":
        confidence = 0.64
    return {
        "ok": True,
        "action": action or "none",
        "confidence": confidence,
        "keyword": matched,
        "question": question,
        "openLoops": loops,
        "reason": "emotioncore-local-activity",
    }


def _person_tag(payload: dict[str, Any]) -> dict[str, Any]:
    qq = str(payload.get("qq") or payload.get("user_id") or "").strip()
    name = str(payload.get("name") or payload.get("display_name") or "").strip()
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    if not qq:
        return {"ok": False, "error": "person_tag needs qq"}
    with _LOCK:
        conn = db.connect(os.environ.get("EMOTIONCORE_DB") or os.environ.get("SOULCORE_DB") or DEFAULT_DB)
        try:
            person = people.tag_person(
                conn,
                user_id=qq,
                display_name=name or qq,
                tags=[str(x) for x in tags if str(x).strip()],
                note=str(payload.get("note") or ""),
            )
            return {"ok": True, "person": person}
        finally:
            conn.close()


def _health() -> dict[str, Any]:
    with _LOCK:
        conn = db.connect(os.environ.get("EMOTIONCORE_DB") or os.environ.get("SOULCORE_DB") or DEFAULT_DB)
        try:
            n = conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]
            p = conn.execute("SELECT COUNT(*) AS c FROM people").fetchone()["c"]
            return {"ok": True, "version": VERSION, "db": DEFAULT_DB, "memories": n, "people": p}
        finally:
            conn.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "EmotionCore/" + VERSION
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict[str, Any]:
        n = int(self.headers.get("content-length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(min(n, 2_000_000))
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/health":
            self._send(200, _health())
            return
        if u.path == "/person":
            qq = (parse_qs(u.query).get("qq") or [""])[0]
            self._send(200, {"ok": True, "person": _people_lookup(qq)})
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        try:
            payload = self._body()
            if u.path == "/context":
                self._send(200, _context(payload))
                return
            if u.path == "/turn":
                self._send(200, _turn(payload))
                return
            if u.path == "/activity":
                self._send(200, _activity(payload))
                return
            if u.path == "/person_tag":
                self._send(200, _person_tag(payload))
                return
            if u.path == "/person_impression":
                self._send(200, _person_impression(payload))
                return
            if u.path == "/recall":
                self._send(200, _recall(payload))
                return
            self._send(404, {"ok": False, "error": "not found"})
        except Exception as e:  # keep the seam alive; logs the error in the response
            self._send(500, {"ok": False, "error": str(e)})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[emotioncore] " + fmt % args + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("EMOTIONCORE_HOST") or "127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--db", default="")
    args = ap.parse_args(argv)
    if args.db:
        os.environ["EMOTIONCORE_DB"] = args.db
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[emotioncore] listening http://{args.host}:{args.port} db={os.environ.get('EMOTIONCORE_DB') or DEFAULT_DB}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
