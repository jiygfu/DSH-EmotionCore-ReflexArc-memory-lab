"""Pre-sleep farewell, sent through the local EmotionCore service.

Historically this went through SurfCore's console bridge; after the move to
OneBot that path is dead (`OneBot-only: SurfCore farewell skipped`). EmotionCore
runs on the same machine and talks to OneBot's HTTP API, so the farewell lives
there now: `POST http://127.0.0.1:8765/farewell`.

Config: data/sleep-farewell.json -> {"enabled": true, "message": "...", "target": "private:<你的QQ号>"}
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent / "data"
DEFAULT = {
    "enabled": True,
    "message": "哼，我去睡了。晚安，明天再说。",
    "target": "",
    "endpoint": "http://127.0.0.1:8765/farewell",
    "reason": "sleep",
}


def config() -> dict[str, Any]:
    out = dict(DEFAULT)
    try:
        raw = json.loads((DATA / "sleep-farewell.json").read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k in out:
                if raw.get(k) is not None:
                    out[k] = raw[k]
    except Exception:
        pass
    return out


def maybe_send(reason: str = "sleep") -> dict[str, Any]:
    cfg = config()
    if cfg.get("enabled") is not True:
        return {"ok": True, "sent": False, "reason": "disabled"}
    message = str(cfg.get("message") or "").strip()
    target = str(cfg.get("target") or "").strip()
    if not message:
        return {"ok": False, "sent": False, "reason": "empty_message"}
    if not target:
        return {"ok": False, "sent": False, "reason": "no_target"}
    body = json.dumps({"message": message, "target": target, "reason": reason}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        str(cfg.get("endpoint") or DEFAULT["endpoint"]),
        data=body,
        method="POST",
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            out = json.loads(resp.read().decode("utf-8", "replace") or "{}")
        return {"ok": bool(out.get("ok")), "sent": bool(out.get("sent")), "via": "emotioncore", "result": out}
    except Exception as e:
        return {"ok": False, "sent": False, "via": "emotioncore", "reason": "emotioncore_unreachable", "error": str(e)}
