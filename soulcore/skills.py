"""Phase A local skill registry.

Only deterministic built-ins are executable. The local model may route later,
but it never authors or executes arbitrary code here.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Callable

from . import consolidate, db, inbox, people, retrieval, social


BUILTINS = [
    {
        "id": "memory.sync_inbox",
        "version": 1,
        "title": "同步 SurfCore inbox",
        "description": "只读导入 memory-inbox.jsonl，保留 senderId。",
        "intent_examples": ["同步记忆", "把群聊记录读进来"],
        "inputs": {"limit": {"type": "integer", "default": 200}},
        "executor": "builtin:sync_inbox",
        "success": ["no_exception"],
    },
    {
        "id": "memory.people_refresh",
        "version": 1,
        "title": "刷新人物关系",
        "description": "按当天 appraisal 刷新人物 trust/valence/stance。",
        "intent_examples": ["刷新人物关系", "更新群友印象"],
        "inputs": {"day": {"type": "string", "default": ""}},
        "executor": "builtin:people_refresh",
        "success": ["no_exception"],
    },
    {
        "id": "memory.consolidate",
        "version": 1,
        "title": "日终记忆巩固",
        "description": "计算 ambient，清洗低重要度情感权重。",
        "intent_examples": ["整理今天的记忆", "睡前整理"],
        "inputs": {"mode": {"type": "string", "default": "day_end"}},
        "executor": "builtin:consolidate",
        "success": ["no_exception"],
    },
    {
        "id": "memory.recall",
        "version": 1,
        "title": "按文本检索记忆",
        "description": "用本地 n-gram 检索并更新熟悉度。",
        "intent_examples": ["回忆一下", "检索记忆"],
        "inputs": {"text": {"type": "string", "required": True}, "limit": {"type": "integer", "default": 6}},
        "executor": "builtin:recall",
        "success": ["no_exception"],
    },
]


def _exec_sync_inbox(conn: sqlite3.Connection, args: dict[str, Any]) -> Any:
    return inbox.sync_inbox(
        conn,
        surfcore_root=args.get("surfcore_root") or None,
        limit=int(args.get("limit") or 200),
        include_self=args.get("include_self", True) is not False,
    )


def _exec_people_refresh(conn: sqlite3.Connection, args: dict[str, Any]) -> Any:
    return people.refresh(conn, day=args.get("day") or None)


def _exec_consolidate(conn: sqlite3.Connection, args: dict[str, Any]) -> Any:
    result = consolidate.run(conn, mode=str(args.get("mode") or "day_end"), dry_run=bool(args.get("dry_run")))
    return {k: v for k, v in result.items() if k != "details"}


def _exec_recall(conn: sqlite3.Connection, args: dict[str, Any]) -> Any:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ValueError("recall requires text")
    return retrieval.retrieve(conn, text, limit=int(args.get("limit") or 6), mark=True)


EXECUTORS: dict[str, Callable[[sqlite3.Connection, dict[str, Any]], Any]] = {
    "builtin:sync_inbox": _exec_sync_inbox,
    "builtin:people_refresh": _exec_people_refresh,
    "builtin:consolidate": _exec_consolidate,
    "builtin:recall": _exec_recall,
}


def register_builtins(conn: sqlite3.Connection) -> int:
    now = db.utcnow()
    n = 0
    for s in BUILTINS:
        cur = conn.execute(
            """INSERT OR IGNORE INTO skills
               (id, version, title, description, intent_examples_json, inputs_json,
                executor, success_json, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (s["id"], s["version"], s["title"], s["description"],
             json.dumps(s["intent_examples"], ensure_ascii=False),
             json.dumps(s["inputs"], ensure_ascii=False), s["executor"],
             json.dumps(s["success"], ensure_ascii=False), now, now),
        )
        n += int(cur.rowcount > 0)
    conn.commit()
    return n


def list_skills(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, version, title, description, executor, status FROM skills ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def route(conn: sqlite3.Connection, text: str) -> dict[str, Any] | None:
    """Rule-first routing; the local model can be added for ambiguity later."""
    q = (text or "").strip()
    if not q:
        return None
    rules = [
        ("同步", "memory.sync_inbox"),
        ("读进来", "memory.sync_inbox"),
        ("人物", "memory.people_refresh"),
        ("群友", "memory.people_refresh"),
        ("整理", "memory.consolidate"),
        ("睡前", "memory.consolidate"),
        ("回忆", "memory.recall"),
        ("检索", "memory.recall"),
    ]
    for needle, skill_id in rules:
        if needle in q:
            return {"skill_id": skill_id, "confidence": 0.8, "reason": f"rule:{needle}"}
    return None


def _record_skill_memory(
    conn: sqlite3.Connection,
    *,
    skill_id: str,
    version: int,
    ok: bool,
    summary: str,
    run_id: int,
) -> str:
    text = (
        f"技能 {skill_id} v{version} {'成功' if ok else '失败'}：{summary}"
    )
    mid, _ = db.upsert_memory(
        conn,
        source="skill",
        source_record_id=f"run:{run_id}",
        text=text,
        scope="skill",
        sensitive=False,
        importance=0.2 if ok else 0.5,
        speaker="skill",
        identity_status="system",
        raw={"skill_id": skill_id, "version": version, "ok": ok, "run_id": run_id},
    )
    return mid


def _maybe_request(conn: sqlite3.Connection, skill_id: str, version: int, last_error: str) -> int | None:
    rows = conn.execute(
        """SELECT id FROM skill_runs WHERE skill_id=? AND ok=0
           ORDER BY id DESC LIMIT 3""",
        (skill_id,),
    ).fetchall()
    if len(rows) < 3:
        return None
    pending = conn.execute(
        "SELECT id FROM skill_requests WHERE skill_id=? AND status='pending' LIMIT 1",
        (skill_id,),
    ).fetchone()
    if pending:
        return int(pending["id"])
    cur = conn.execute(
        """INSERT INTO skill_requests
           (skill_id, version, failures, last_error, evidence_json, status, created_at)
           VALUES (?, ?, 3, ?, ?, 'pending', ?)""",
        (skill_id, version, last_error[:500],
         json.dumps([r["id"] for r in rows], ensure_ascii=False), db.utcnow()),
    )
    conn.commit()
    return int(cur.lastrowid)


def run(
    conn: sqlite3.Connection,
    skill_id: str,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    args = args or {}
    skill = conn.execute("SELECT * FROM skills WHERE id=? AND status='active'", (skill_id,)).fetchone()
    if not skill:
        raise ValueError(f"skill not found: {skill_id}")
    executor = EXECUTORS.get(skill["executor"])
    if not executor:
        raise ValueError(f"executor not registered: {skill['executor']}")
    start = time.perf_counter()
    try:
        result = executor(conn, args)
        latency = int((time.perf_counter() - start) * 1000)
        cur = conn.execute(
            """INSERT INTO skill_runs
               (skill_id, version, ok, latency_ms, input_json, result_json, error, created_at)
               VALUES (?, ?, 1, ?, ?, ?, NULL, ?)""",
            (skill_id, int(skill["version"]), latency,
             json.dumps(args, ensure_ascii=False)[:4000],
             json.dumps(result, ensure_ascii=False)[:8000], db.utcnow()),
        )
        run_id = int(cur.lastrowid)
        conn.commit()
        summary = "完成"
        if isinstance(result, dict):
            if "new" in result:
                summary = f"新增 {result.get('new')} 条"
            elif "updated" in result:
                summary = f"更新 {result.get('updated')} 人"
        mid = _record_skill_memory(
            conn, skill_id=skill_id, version=int(skill["version"]),
            ok=True, summary=summary, run_id=run_id,
        )
        return {"ok": True, "run_id": run_id, "result": result, "outcome_memory": mid}
    except Exception as exc:
        latency = int((time.perf_counter() - start) * 1000)
        cur = conn.execute(
            """INSERT INTO skill_runs
               (skill_id, version, ok, latency_ms, input_json, result_json, error, created_at)
               VALUES (?, ?, 0, ?, ?, NULL, ?, ?)""",
            (skill_id, int(skill["version"]), latency,
             json.dumps(args, ensure_ascii=False)[:4000],
             str(exc)[:1000], db.utcnow()),
        )
        run_id = int(cur.lastrowid)
        conn.commit()
        mid = _record_skill_memory(
            conn, skill_id=skill_id, version=int(skill["version"]),
            ok=False, summary=str(exc)[:200], run_id=run_id,
        )
        req = _maybe_request(conn, skill_id, int(skill["version"]), str(exc))
        return {
            "ok": False, "run_id": run_id, "error": str(exc)[:1000],
            "outcome_memory": mid, "request_id": req,
        }
