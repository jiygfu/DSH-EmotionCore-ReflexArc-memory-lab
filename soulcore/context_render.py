"""Render a compact local context block for the speaking layer.

This file is prepared for a future SurfCore prompt seam. It is not injected into
SurfCore yet; no SurfCore code or memory is modified.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from . import body_state, db, desire, people, personality

DEFAULT_CONTEXT_FILE = Path(
    os.environ.get("SOULCORE_CONTEXT_FILE")
    or (Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh"))) / "surfcore" / "soulcore-context.md")
)
DEFAULT_BILI_CONTEXT_FILE = Path(
    os.environ.get("SOULCORE_BILI_CONTEXT_FILE")
    or (Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh"))) / "surfcore" / "soulcore-context-bili.md")
)

DIM_LABELS = {
    "security": "安全感",
    "trust": "信任",
    "self_efficacy": "自我效能",
    "caution": "警觉",
    "sociability": "社交倾向",
    "openness": "开放",
    "valence": "效价",
    "arousal": "唤醒",
}


def _p_words(p: dict) -> str:
    """把 P 翻成表意识能用的词；数字只留给本地评价层。"""
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
    return "，".join(bits)


def render(
    conn: sqlite3.Connection,
    *,
    day: str | None = None,
    max_person: int = 4,
    max_chars: int = 1800,
    include_people: bool = True,
) -> str:
    d = day or datetime.now().astimezone().date().isoformat()
    p = personality.compute_p(conn)
    lines = ["【SoulCore 潜意识状态（背景，不主动解释）】"]
    lines.append(f"现在大致是：{_p_words(p['p'])}。")
    lines.append("这不是台词，只是你此刻的倾向。")
    lines.append("旧记忆中 identity_status=legacy_unresolved/self 的说话人不明确：不要默认归给主人，也不要用想象补。")
    try:
        pending_count = conn.execute(
            "SELECT COUNT(*) AS c FROM appraisal_questions WHERE status='pending'"
        ).fetchone()["c"]
    except Exception:
        pending_count = 0
    if pending_count:
        lines.append(
            f"【SoulCore 待确认】有 {pending_count} 条记忆的本地评分失败/不确定；"
            "需要时用 soulcore_memory 的 questions/resolve 查看并给出表层评分。"
        )
    if not include_people:
        lines.append("公开平台：不携带 QQ 群友人物卡，保持平台隐私边界。")

    cards = people.today_people(conn, day=d, limit=max_person) if include_people else []
    if cards:
        lines.append("")
        lines.append("【今天被触发的人（关系是背景，不主动解释）】")
        for c in cards:
            name = c.get("display_name") or c.get("id")
            profile = c.get("profile") or {}
            bits = [
                f"{name}：熟悉度 {c['familiarity']:.2f}，信任 {c['trust']:.2f}，"
                f"效价 {c['valence']:+.2f}，未解决 {c['unresolved']:.2f}。"
            ]
            if (c.get("today") or {}).get("summary"):
                bits.append(f"今日：{c['today']['summary']}")
            if profile.get("summary"):
                bits.append(f"侧写（草稿）：{profile['summary']}")
            if c.get("action_hint"):
                bits.append(c["action_hint"])
            lines.append("- " + " ".join(bits))
    try:
        hint = body_state.snapshot(write=False).get("surface_hint") or ""
        m = re.search(r"（API 余额约 ([0-9.]+)）", hint)
        if m:
            try:
                if float(m.group(1)) >= 5:
                    hint = re.sub(r"（API 余额约 [0-9.]+）", "", hint)
                else:
                    hint = hint.replace(m.group(0), "（API 余额不多了，像快没饭吃）")
            except Exception:
                pass
        if hint:
            lines.append(hint)
    except Exception:
        pass
    try:
        dh = desire.compute(conn).get("surface_hint") or ""
        if dh:
            lines.append(dh)
    except Exception:
        pass
    text = "\n".join(lines).strip()
    return text[:max(400, int(max_chars))]


def write(
    conn: sqlite3.Connection,
    out: str | Path | None = None,
    *,
    day: str | None = None,
    include_people: bool = True,
) -> str:
    text = render(conn, day=day, include_people=include_people)
    path = Path(out) if out else DEFAULT_CONTEXT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return str(path)


def write_bili(conn: sqlite3.Connection, out: str | Path | None = None, *, day: str | None = None) -> str:
    return write(conn, out or DEFAULT_BILI_CONTEXT_FILE, day=day, include_people=False)
