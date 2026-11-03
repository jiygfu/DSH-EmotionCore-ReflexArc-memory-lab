"""Deterministic sleep handoff: facts the local body can verify.

This is intentionally not another LLM summary. It points at the latest
episode/raw memory, the sleep ledger, pending questions and the current
P/desire delta so the surface layer starts from evidence instead of an
identity declaration.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from . import body_state, daybook, db, desire, personality

DATA = Path(__file__).resolve().parent.parent / "data"
MAX_CHARS = 900


def _local(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt.astimezone().strftime("%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _place(conversation_key: str | None) -> str:
    key = str(conversation_key or "")
    if key.startswith("private:"):
        return "私聊"
    if key.startswith("group:"):
        return "群聊"
    return key


def _latest_episode(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT id, day, start_at, end_at, conversation_key, summary, key_quote,
                  felt, unresolved, importance
           FROM episodes
           WHERE importance > 0
             AND source_kind != 'reflection'
           ORDER BY COALESCE(end_at, start_at, created_at) DESC LIMIT 1"""
    ).fetchone()
    return dict(row) if row else None


def _latest_memory(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT id, ts, scope, conversation_key, speaker, text, identity_status
           FROM memories WHERE COALESCE(sensitive,0)=0 AND status='active'
           ORDER BY COALESCE(ts, created_at) DESC LIMIT 1"""
    ).fetchone()
    return dict(row) if row else None


def _sleep(conn: sqlite3.Connection) -> dict[str, Any]:
    day = _today()
    try:
        rows = conn.execute(
            "SELECT day_key, reason, at FROM sleep_runs WHERE day_key=? AND reason IN ('sleep','daily') ORDER BY id ASC",
            (day,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    last = None
    try:
        last = conn.execute(
            "SELECT day_key, reason, at FROM sleep_runs WHERE reason IN ('sleep','daily') ORDER BY id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        pass
    return {
        "count_today": len(rows),
        "last_at": (dict(last) if last else {}).get("at"),
        "last_day": (dict(last) if last else {}).get("day_key"),
    }


def _pending(conn: sqlite3.Connection) -> int:
    try:
        return int(conn.execute(
            "SELECT COUNT(*) FROM appraisal_questions WHERE status='pending'"
        ).fetchone()[0])
    except sqlite3.OperationalError:
        return 0


def _p_delta(conn: sqlite3.Connection) -> tuple[dict[str, float], str]:
    """Coarse slow-P shift; day summary delta is preferred."""
    day = _today()
    delta: dict[str, float] = {}
    try:
        summary = daybook.latest(conn, day)
        if summary and isinstance(summary.get("delta"), dict):
            delta = {k: round(float(v), 3) for k, v in summary["delta"].items()}
    except Exception:
        pass
    if not delta:
        try:
            current = personality.compute_p(conn).get("p") or {}
            baseline = daybook.latest(conn, day)
            if baseline and isinstance(baseline.get("baseline"), dict):
                delta = {
                    k: round(float(current.get(k, 0.0)) - float(baseline["baseline"].get(k, 0.0)), 3)
                    for k in personality.DIMENSIONS
                }
        except Exception:
            delta = {}
    return delta, ("day_delta" if delta else "unavailable")


def _top_delta(delta: dict[str, float], threshold: float = 0.06) -> list[tuple[str, float]]:
    return sorted(
        ((k, v) for k, v in delta.items() if abs(float(v)) >= threshold),
        key=lambda kv: abs(float(kv[1])),
        reverse=True,
    )[:2]


def _desires(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        return list(desire.compute(conn).get("desires") or [])[:2]
    except Exception:
        return []


def _who(conn: sqlite3.Connection) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for scope in ("private", "group"):
        try:
            row = conn.execute(
                """SELECT speaker, text, conversation_key, ts FROM memories
                   WHERE scope=? AND COALESCE(sensitive,0)=0 AND status='active'
                   ORDER BY COALESCE(ts, created_at) DESC LIMIT 1""",
                (scope,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row:
            out[scope] = dict(row)
    return out


def _body() -> dict[str, Any]:
    try:
        snap = body_state.snapshot(write=False)
        raw = snap.get("raw") or {}
        return {
            "balance": raw.get("balance"),
            "cpu_pct": raw.get("cpu_pct"),
            "mem_pct": raw.get("mem_pct"),
            "temporary_only": True,
        }
    except Exception:
        return {}


def _loops_line(limit: int = 2) -> str:
    """未完成事件（读桥接写的 loops.jsonl，只读）。"""
    try:
        from . import patience

        loops = [x for x in patience._load_loops() if x.get("status") in ("open", "paused", "waiting")]
    except Exception:
        loops = []
    if not loops:
        return "- 没接完的：没有。"
    import datetime as _dt

    now = int(_dt.datetime.now().timestamp() * 1000)
    due = [x for x in loops if x.get("anchor_at") and int(x["anchor_at"]) <= now]
    rest = [x for x in loops if x not in due]
    picked = []
    if due:
        picked.append(f"「{due[0].get('one_line') or ''}」（时间到了）")
    for x in rest:
        if len(picked) >= limit:
            break
        picked.append(f"「{x.get('one_line') or ''}」")
    if not picked:
        return "- 没接完的：没有。"
    return f"- 没接完的：{'；'.join(picked)}。"


def _state_words(p: dict[str, Any]) -> str:
    """把数值翻成自然语言。表意识不需要看到 0.42 这种数。"""
    bits = []
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
    sec = float(p.get("security", 0) or 0)
    if sec > 0.6:
        bits.append("心里踏实")
    elif sec < 0.4:
        bits.append("有点没底")
    op = float(p.get("openness", 0) or 0)
    if op > 0.6:
        bits.append("想聊点新的")
    elif op < 0.35:
        bits.append("想守着熟悉的")
    return "，".join(bits)


def build(conn: sqlite3.Connection) -> dict[str, Any]:
    episode = _latest_episode(conn)
    memory = _latest_memory(conn)
    sleep = _sleep(conn)
    pending = _pending(conn)
    delta, delta_source = _p_delta(conn)
    top_delta = _top_delta(delta)
    desires = _desires(conn)
    who = _who(conn)
    body = _body()

    lines = ["【交接｜刚睡醒】", "你刚结束一次睡眠整理，现在接回 QQ。"]
    if episode:
        where = _place(episode.get("conversation_key"))
        when = _local(episode.get("end_at") or episode.get("start_at"))
        lines.append(f"- 上次停在：{when}{('，' + where) if where else ''}。")
        lines.append(f"  体感摘要：{str(episode.get('summary') or '')[:160]}")
    elif memory:
        lines.append(f"- 上次停在：{_local(memory.get('ts'))}，{_place(memory.get('conversation_key')) or '某处'}。")
    lines.append(_loops_line())
    if sleep["count_today"]:
        lines.append(
            f"- 今天这是第 {sleep['count_today']} 次睡眠；上次睡眠结束 {_local(sleep['last_at'])}。"
        )
    else:
        lines.append("- 今天还没有更早的睡眠记录。")
    if who.get("private"):
        p = who["private"]
        lines.append(f"- 最近私聊：{p.get('speaker') or '对方'}：{str(p.get('text') or '')[:80]}")
    if who.get("group"):
        g = who["group"]
        lines.append(f"- 最近群聊：{g.get('speaker') or '对方'}：{str(g.get('text') or '')[:80]}")
    if body.get("balance") is not None:
        lines.append(f"- 身体：API 余额约 {body['balance']}；这些只是临时状态。")

    p_now = {}
    try:
        p_now = personality.compute_p(conn).get("p") or {}
    except Exception:
        p_now = {}
    if p_now:
        lines.append(f"- 现在的状态：{_state_words(p_now)}。这是慢变量，不是命令。")
    if desires:
        d = desires[0]
        tier = "轻量念头" if d.get("tier") == "micro" else "欲望"
        lines.append(
            f"- 身体现在给的{tier}：{d.get('hint')} "
            f"（原因：{d.get('why')}；强度 {d.get('urgency')}）"
        )

    lines.extend([
        "",
        "【现在】",
        "先看有没有新消息；有就接，没有就做自己的事。",
        "",
        "【可以核对】",
        "需要旧事时用当前通道可用的本地记忆查询；旧的 soulcore_memory 入口已下线。",
        "这些是交接线索，不是要求你相信的宣告。",
        "",
        "【不用担心睡醒后记忆模糊】",
        "人类也这样。",
    ])
    text = "\n".join(lines).strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rstrip() + "\n…"
    return {
        "schema": "emotioncore.handoff.v1",
        "at": db.localnow(),
        "episode": episode,
        "memory": memory,
        "sleep": sleep,
        "pending_questions": pending,
        "p_delta": delta,
        "p_delta_source": delta_source,
        "desires": desires,
        "body": body,
        "text": text,
    }


def write(conn: sqlite3.Connection, *, out: str | Path | None = None) -> dict[str, Any]:
    data = build(conn)
    target = Path(out) if out else (DATA / "handoff.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data["text"] + "\n", encoding="utf-8")
    (DATA / "handoff.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    data["path"] = str(target)
    return data
