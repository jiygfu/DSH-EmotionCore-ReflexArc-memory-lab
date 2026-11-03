"""Optional owner feedback via SurfCore's existing console send endpoint.

No new transport: this reuses the bridge's existing /api/test-send route and
falls back to a local question file when the bridge is unavailable.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SURFCORE_ROOT = Path.home() / ".dsh" / "surfcore"
CONFIG_FILE = SURFCORE_ROOT / "config.json"
FALLBACK_FILE = Path(__file__).resolve().parent.parent / "data" / "appraisal-questions.jsonl"


def _config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fallback(message: str, error: str) -> None:
    FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with FALLBACK_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "at": __import__("datetime").datetime.now().astimezone().isoformat(),
            "message": message,
            "error": error,
        }, ensure_ascii=False) + "\n")


def send_private(message: str, *, timeout: int = 8) -> dict[str, Any]:
    """Send a plain private message through the existing bridge test-send route."""
    cfg = _config()
    owner = str(cfg.get("ownerQQ") or "").strip()
    if not owner:
        _fallback(message, "ownerQQ missing")
        return {"ok": False, "error": "ownerQQ missing", "fallback": str(FALLBACK_FILE)}
    port = int(cfg.get("consolePort") or 3100)
    token = str(cfg.get("consoleToken") or "")
    body = json.dumps({
        "kind": "private",
        "id": int(owner) if owner.isdigit() else owner,
        "message": message[:500],
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/test-send",
        data=body,
        headers={"content-type": "application/json", "x-console-token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        if data.get("ok"):
            return {"ok": True, "via": "surfcore-test-send", "data": data}
        _fallback(message, str(data))
        return {"ok": False, "via": "surfcore-test-send", "error": data, "fallback": str(FALLBACK_FILE)}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        _fallback(message, str(exc))
        return {"ok": False, "via": "surfcore-test-send", "error": str(exc), "fallback": str(FALLBACK_FILE)}


def ask_owner(message: str, error: str = "", *, timeout: int = 8) -> dict[str, Any]:
    """Use the existing bridge console route; never raise into appraisal."""
    return send_private(message, timeout=timeout)
