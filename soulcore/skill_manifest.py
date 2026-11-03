"""Fixed-program skill manifest for the current session.

No model call, no network. Capabilities are filtered here; the main model gets
the compact list once at bootstrap, not on every turn.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent / "data"
SURFCORE_HOME = Path.home() / ".dsh" / "surfcore"

DEFAULT_CAPABILITIES = {"qq": True, "pet": False, "bili": False}
DEFAULT_SKILLS = [
    {"id": "qq_chat", "name": "QQ 对话", "when": "回复、引用、等待、已读、收尾", "caps": ["qq"], "tools": ["qq_send_message", "qq_reply", "qq_wait_for_messages", "qq_mark_read", "qq_close_conversation"]},
    {"id": "qq_sticker", "name": "QQ 表情包", "when": "接梗、安慰、告别、表达情绪", "caps": ["qq"], "tools": ["qq_send_sticker", "qq_list_stickers"]},
    {"id": "memory", "name": "长期记忆", "when": "被问记得什么、要查旧事/人物", "caps": ["qq"], "tools": ["soulcore_memory"]},
    {"id": "memory_resolve", "name": "记忆修正", "when": "有疑问需要表层评分/问 owner", "caps": ["qq"], "tools": ["soulcore_memory(resolve)"]},
    {"id": "purpose", "name": "主动搭话", "when": "目的机制自动运行，不需要手动调用", "caps": ["qq"], "tools": []},
    {"id": "pet_chat", "name": "桌宠对话", "when": "桌宠私聊", "caps": ["pet"], "tools": ["pet_chat"]},
    {"id": "bili", "name": "B站生物钟", "when": "B站刷视频/评论/动态", "caps": ["bili"], "tools": ["bili"]},
]


def _bridge_root() -> Path | None:
    try:
        cfg = json.loads((SURFCORE_HOME / "config.json").read_text(encoding="utf-8"))
        root = Path(str(cfg.get("qqbotRoot") or "")).expanduser()
        return root if root else None
    except Exception:
        return None


def _state_dir() -> Path:
    root = _bridge_root()
    return (root / "state") if root else (SURFCORE_HOME / "state")


def load_capabilities() -> dict[str, bool]:
    caps = dict(DEFAULT_CAPABILITIES)
    try:
        raw = json.loads((DATA / "capabilities.json").read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k in caps:
                if isinstance(raw.get(k), bool):
                    caps[k] = raw[k]
    except Exception:
        pass
    return caps


def load_skills() -> list[dict[str, Any]]:
    try:
        raw = json.loads((DATA / "skills.json").read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict) and x.get("id")]
    except Exception:
        pass
    return list(DEFAULT_SKILLS)


def build() -> dict[str, Any]:
    caps = load_capabilities()
    skills = [s for s in load_skills() if all(caps.get(c, False) for c in (s.get("caps") or []))]
    lines = ["【可用技能（本会话只加载一次；需要细节再打开）】"]
    for s in skills:
        tools = s.get("tools") or []
        tail = f"（{', '.join(str(t) for t in tools[:6])}）" if tools else ""
        lines.append(f"- {s.get('name') or s['id']}：{s.get('when') or '需要时使用'}{tail}")
    text = "\n".join(lines)
    if len(text) > 1500:
        text = text[:1490] + "\n…"
    version_src = json.dumps({"caps": caps, "skills": skills}, ensure_ascii=False, sort_keys=True)
    return {
        "schema": "emotioncore.skill-manifest.v1",
        "capabilities": caps,
        "skills": skills,
        "text": text,
        "version": hashlib.sha1(version_src.encode("utf-8")).hexdigest()[:12],
        "chars": len(text),
    }


def write() -> dict[str, Any]:
    data = build()
    state = _state_dir()
    state.mkdir(parents=True, exist_ok=True)
    (state / "skill-manifest.md").write_text(data["text"] + "\n", encoding="utf-8")
    (state / "soulcore-capabilities.json").write_text(
        json.dumps(data["capabilities"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"ok": True, "dir": str(state), **{k: data[k] for k in ("version", "chars", "capabilities", "text")}}
