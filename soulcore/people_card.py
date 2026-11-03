"""一人一档（M5）：把 people / person_profiles / person_impressions / 最近记忆
渲染成一份可读的 Markdown，外加一份 ≤200 字的"注入版"。

设计边界（qq-master-plan.md §6.6）：
  · 只渲染、不改数据；DB 仍是唯一真相；
  · 心理猜测必须标"我的感觉"，不能写成事实；
  · 注入版只给当前对话对象，且只给熟人（门槛在桥接侧判断）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent / "data"
CARDS = DATA / "people"
INJECT = Path.home() / ".dsh" / "surfcore" / "people"

STANCE_LABEL = {
    "build": "在经营这段关系",
    "casual": "普通来往",
    "cold": "有点冷",
    "avoid": "在回避",
}

MAX_INJECT_CHARS = 200


def _row(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    try:
        return conn.execute(sql, params).fetchall()
    except Exception:
        return []


def _profile(conn: sqlite3.Connection, person_id: str) -> dict[str, Any] | None:
    rows = _row(
        conn,
        "SELECT personality, speaking_style, hobbies_json, summary, confidence, status "
        "FROM person_profiles WHERE person_id=? ORDER BY version DESC LIMIT 1",
        (person_id,),
    )
    if not rows:
        return None
    r = rows[0]
    try:
        hobbies = json.loads(r["hobbies_json"] or "[]")
    except Exception:
        hobbies = []
    return {
        "personality": r["personality"] or "",
        "speaking_style": r["speaking_style"] or "",
        "hobbies": hobbies,
        "summary": r["summary"] or "",
        "confidence": float(r["confidence"] or 0),
        "status": r["status"] or "draft",
    }


def _impressions(conn: sqlite3.Connection, person_id: str, limit: int = 2) -> list[dict[str, Any]]:
    rows = _row(
        conn,
        "SELECT text, importance, confidence, created_at FROM person_impressions "
        "WHERE person_id=? ORDER BY importance DESC, created_at DESC LIMIT ?",
        (person_id, limit),
    )
    return [dict(r) for r in rows]


def _recent_memories(conn: sqlite3.Connection, person_id: str, limit: int = 3) -> list[dict[str, Any]]:
    rows = _row(
        conn,
        "SELECT ts, speaker, text, conversation_key FROM memories "
        "WHERE person_id=? AND COALESCE(sensitive,0)=0 ORDER BY ts DESC LIMIT ?",
        (person_id, limit),
    )
    return [dict(r) for r in rows]


def _last_talk(conn: sqlite3.Connection, person_id: str) -> str:
    rows = _row(
        conn,
        "SELECT ts, conversation_key FROM memories WHERE person_id=? ORDER BY ts DESC LIMIT 1",
        (person_id,),
    )
    if not rows:
        return ""
    return str(rows[0]["ts"] or "")[:16].replace("T", " ")


def _inject_text(person: dict[str, Any], profile: dict[str, Any] | None, impressions: list[dict[str, Any]]) -> str:
    """注入版：第一人称、猜测带标注、≤200 字。"""
    bits = [f"关于 {person.get('display_name') or person.get('user_id')}："]
    fam = float(person.get("familiarity") or 0)
    stance = STANCE_LABEL.get(str(person.get("stance") or "casual"), "普通来往")
    bits.append(f"熟悉度 {fam:.2f}，{stance}。")
    if profile and profile.get("speaking_style"):
        bits.append(f"说话方式：{profile['speaking_style'][:40]}（我的感觉，不一定对）")
    elif profile and profile.get("personality"):
        bits.append(f"大概是个{profile['personality'][:30]}的人（我的感觉，不一定对）")
    if impressions:
        bits.append(f"印象最深：{impressions[0]['text'][:40]}")
    text = " ".join(bits)
    if len(text) > MAX_INJECT_CHARS:
        text = text[:MAX_INJECT_CHARS].rstrip()
    return text


def build_card(conn: sqlite3.Connection, person_id: str) -> tuple[str, str]:
    """返回 (markdown, 注入版)。"""
    rows = _row(conn, "SELECT * FROM people WHERE id=?", (person_id,))
    if not rows:
        return "", ""
    person = dict(rows[0])
    profile = _profile(conn, person_id)
    impressions = _impressions(conn, person_id)
    recent = _recent_memories(conn, person_id)
    last = _last_talk(conn, person_id)

    lines = [f"# {person.get('display_name') or person.get('user_id')}（{person_id}）", ""]
    lines.append("## 关系")
    lines.append(
        f"熟悉度 {float(person.get('familiarity') or 0):.2f} · 信任 {float(person.get('trust') or 0):.2f} · "
        f"效价 {float(person.get('valence') or 0):+.2f} · 未解决 {float(person.get('unresolved') or 0):.2f} · "
        f"{STANCE_LABEL.get(str(person.get('stance') or 'casual'), '普通来往')} · {int(person.get('message_count') or 0)} 条"
    )
    if last:
        lines.append(f"最近一次：{last}")

    lines += ["", "## 我的感觉（猜测，不是事实）"]
    if profile:
        if profile["personality"]:
            lines.append(f"- 性格：{profile['personality'][:80]}")
        if profile["speaking_style"]:
            lines.append(f"- 说话方式：{profile['speaking_style'][:80]}")
        if profile["hobbies"]:
            lines.append(f"- 在意/喜欢：{'、'.join(str(h) for h in profile['hobbies'][:5])}")
        lines.append(f"（侧写版本 {profile['status']}，置信 {profile['confidence']:.2f}）")
    else:
        lines.append("- 还没有侧写（消息太少，或者还没到生成的时候）")

    lines += ["", "## 印象最深的两件事"]
    if impressions:
        for imp in impressions:
            lines.append(f"- {str(imp['text'])[:100]}")
    else:
        lines.append("- 还没有（我不想编）")

    lines += ["", "## 最近说过的话"]
    if recent:
        for m in recent:
            who = m.get("speaker") or "对方"
            lines.append(f"- {who}：{str(m.get('text') or '')[:80]}")
    else:
        lines.append("- 无记录")

    return "\n".join(lines) + "\n", _inject_text(person, profile, impressions)


def render_all(conn: sqlite3.Connection, *, limit: int = 50) -> dict[str, Any]:
    CARDS.mkdir(parents=True, exist_ok=True)
    INJECT.mkdir(parents=True, exist_ok=True)
    rows = _row(
        conn,
        "SELECT id, user_id, familiarity, is_owner FROM people ORDER BY message_count DESC LIMIT ?",
        (max(1, int(limit)),),
    )
    written = []
    for r in rows:
        md, inject = build_card(conn, r["id"])
        if not md:
            continue
        safe = str(r["user_id"] or r["id"]).replace("/", "_")
        (CARDS / f"{safe}.md").write_text(md, encoding="utf-8")
        if inject:
            (INJECT / f"{safe}.txt").write_text(inject + "\n", encoding="utf-8")
            meta = {
                "id": r["id"],
                "familiarity": float(r["familiarity"] or 0),
                "isOwner": bool(r["is_owner"]),
                "updatedAt": int(__import__("time").time() * 1000),
            }
            (INJECT / f"{safe}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        written.append({"id": r["id"], "file": str(CARDS / f"{safe}.md")})
    return {"ok": True, "people": len(written), "written": written, "injectDir": str(INJECT)}
