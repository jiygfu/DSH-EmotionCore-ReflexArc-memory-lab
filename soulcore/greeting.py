#!/usr/bin/env python3
"""Local morning / night greeting scheduler.

No model call, no prompt/context change. The maintenance worker checks the
local clock and sends one owner-private OneBot message through the existing
SnowLuma HTTP endpoint. Delivery state is stored locally to avoid repeats.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SETTINGS = DATA / "soul-bridge-settings.json"
STATE = DATA / "greeting-state.json"
ONEBOT_CONFIG = Path(os.environ.get("DSH_ONEBOT_CONFIG") or (Path.home() / ".dsh" / "dsh-onebot-qq" / "config.json"))

DEFAULTS = {
    "morningGreetingEnabled": True,
    "morningGreetingTime": "08:30",
    "morningGreetingText": "早，醒了。今天也慢慢来。",
    "nightGreetingEnabled": True,
    "nightGreetingTime": "23:00",
    "nightGreetingText": "夜深了，我去睡了。晚安。",
}

WINDOW = timedelta(hours=2)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def settings() -> dict[str, Any]:
    out = dict(DEFAULTS)
    out.update(_read_json(SETTINGS))
    return out


def _state() -> dict[str, Any]:
    return _read_json(STATE)


def _save_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, STATE)


def _time(value: Any, fallback: str) -> tuple[int, int]:
    try:
        h, m = str(value or fallback).split(":", 1)
        hh, mm = int(h), int(m)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except Exception:
        pass
    h, m = fallback.split(":", 1)
    return int(h), int(m)


def _onebot() -> dict[str, Any]:
    cfg = _read_json(ONEBOT_CONFIG)
    ob = cfg.get("onebot") if isinstance(cfg.get("onebot"), dict) else {}
    return {
        "httpUrl": str(ob.get("httpUrl") or ""),
        "httpToken": str(ob.get("httpToken") or ""),
        "adminQq": cfg.get("adminQq"),
    }


def _send(qq: Any, text: str, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"ok": True, "dry_run": True}
    ob = _onebot()
    url = ob["httpUrl"].rstrip("/") + "/send_private_msg"
    if not ob["httpUrl"] or not qq:
        return {"ok": False, "error": "onebot httpUrl/adminQq missing"}
    body = json.dumps({"user_id": int(qq), "message": text, "auto_escape": True}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if ob["httpToken"]:
        headers["Authorization"] = "Bearer " + ob["httpToken"]
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return {"ok": bool(data.get("status") == "ok" or data.get("retcode") == 0), "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def maybe_send(kind: str, *, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
    """kind: morning | night. Returns skipped/sent/failed without raising."""
    if kind not in ("morning", "night"):
        return {"ok": False, "error": "unknown greeting kind"}
    cfg = settings()
    key = "morning" if kind == "morning" else "night"
    if cfg.get(f"{key}GreetingEnabled") is not True:
        return {"ok": True, "skipped": "disabled"}
    now = now or datetime.now().astimezone()
    hh, mm = _time(cfg.get(f"{key}GreetingTime"), DEFAULTS[f"{key}GreetingTime"])
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < target:
        return {"ok": True, "skipped": "before_time"}
    if now >= target + WINDOW:
        return {"ok": True, "skipped": "window_passed"}
    st = _state()
    day = now.date().isoformat()
    if st.get(f"{key}_date") == day:
        return {"ok": True, "skipped": "already_sent"}
    text = str(cfg.get(f"{key}GreetingText") or DEFAULTS[f"{key}GreetingText"]).strip()
    if not text:
        return {"ok": True, "skipped": "empty_message"}
    ob = _onebot()
    result = _send(ob.get("adminQq"), text, dry_run=dry_run)
    if result.get("ok"):
        if not dry_run:
            st[f"{key}_date"] = day
            st[f"{key}_at"] = now.isoformat()
            _save_state(st)
        return {"ok": True, "sent": True, "kind": kind, "at": now.isoformat(), "result": result}
    return {"ok": False, "sent": False, "kind": kind, "error": result.get("error") or "send failed"}


def run_due(*, now: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    return {
        "morning": maybe_send("morning", now=now, dry_run=dry_run),
        "night": maybe_send("night", now=now, dry_run=dry_run),
    }
