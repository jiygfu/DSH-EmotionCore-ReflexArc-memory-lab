"""Optional pre-sleep private farewell.

This is deliberately outside the appraisal/memory path: it only sends one
outgoing private message before sessions are rotated. If the bridge is down it
falls back to the existing feedback file and never blocks sleep.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import feedback

DATA = Path(__file__).resolve().parent.parent / "data"
DEFAULT = {
    "enabled": False,
    "message": "哼，我去睡了。晚安，明天再说。",
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
    if not message:
        return {"ok": False, "sent": False, "reason": "empty_message"}
    result = feedback.send_private(message)
    return {"sent": bool(result.get("ok")), "result": result, "reason": reason}
