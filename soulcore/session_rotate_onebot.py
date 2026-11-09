"""OneBot 会话轮换：睡眠整理之后把 QQ 侧那条共享会话换掉。

为什么单独一个模块：旧的 `session_rotation.py` 走的是 SurfCore 桥的
`POST /api/session/reset`（带 console token 的 HTTP 服务），OneBot 这套根本没有那个
服务；于是 `cli.cmd_sleep` 里直接写成了 `"OneBot-only: SurfCore session rotation skipped"`
——睡眠照跑、轮换永远跳过，上下文只进不出，162 轮 3 万 token 就是这么堆起来的。

现在的做法分两段，互相兜底：
  1. 这里写一个 pending 标记（`state/session-rotate-pending.json`）；
  2. 反射弧在下一次 before-turn 读到标记 → 归档旧会话 + 删映射 + 清线状态
     （跟 `/reset` 命令同一个动作，所以旧会话会进侧栏而不是变游离）。
机器人没在线也不丢：标记留着，等它下次醒来第一件事就是换会话。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_HOME = Path.home() / ".dsh" / "dsh-onebot-qq"


def home() -> Path:
    for env in ("ONEBOT_HOME", "DSH_ONEBOT_HOME", "SOULCORE_ONEBOT_HOME"):
        raw = str(os.environ.get(env) or "").strip()
        if raw:
            return Path(raw).expanduser()
    return DEFAULT_HOME


def state_dir() -> Path:
    return home() / "state"


def sessions_path() -> Path | None:
    """优先 `state/sessions.json`；兼容老结构里的 `sessions` 字段。"""
    for name in ("sessions.json",):
        p = state_dir() / name
        if p.exists():
            return p
    return None


def pending_path() -> Path:
    return state_dir() / "session-rotate-pending.json"


def read_sessions() -> dict[str, Any]:
    p = sessions_path()
    if not p:
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(raw, dict) and isinstance(raw.get("sessions"), dict):
        return dict(raw["sessions"])
    return raw if isinstance(raw, dict) else {}


def current_session_id() -> str:
    data = read_sessions()
    return str(data.get("__single__") or "")


def pending() -> dict[str, Any] | None:
    p = pending_path()
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"reason": "unknown"}
    except Exception:
        return {"reason": "unreadable"}


def request(reason: str = "sleep", *, sid: str = "") -> dict[str, Any]:
    """挂一个轮换请求。幂等：已有 pending 就合并，不重复写。"""
    state_dir().mkdir(parents=True, exist_ok=True)
    prev = pending() or {}
    payload = {
        "reason": str(reason or "sleep"),
        "sid": str(sid or current_session_id() or prev.get("sid") or ""),
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "requests": int(prev.get("requests") or 0) + 1,
    }
    pending_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "queued": True, **payload, "path": str(pending_path())}


def clear_pending() -> None:
    try:
        pending_path().unlink(missing_ok=True)
    except OSError:
        pass


def rotate_mapping_now(key: str = "__single__") -> dict[str, Any]:
    """兜底：反射弧一直没醒来时，直接把映射删掉（旧会话会留在侧栏，不归档）。"""
    data = read_sessions()
    if key not in data:
        return {"ok": False, "error": f"没有 {key} 的映射", "keys": list(data)}
    old = str(data.pop(key) or "")
    p = sessions_path()
    if not p:
        return {"ok": False, "error": "找不到 sessions.json"}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "removed": key, "old_session": old, "remaining": list(data)}


def status() -> dict[str, Any]:
    return {
        "home": str(home()),
        "sessions": read_sessions(),
        "pending": pending(),
        "pending_path": str(pending_path()),
    }
