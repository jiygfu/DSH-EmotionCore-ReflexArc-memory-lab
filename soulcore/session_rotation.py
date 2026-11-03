"""Rotate SurfCore's per-conversation DSH sessions after sleep cleanup.

Reuses the bridge's existing console API:
  GET  /api/sessions
  POST /api/session/reset {key}

A reset stops/archives the old DSH session and removes the key mapping; the next
incoming message creates a fresh session. Memory cards/sidecar/context survive.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SURFCORE_HOME = Path.home() / ".dsh" / "surfcore"
PENDING = SURFCORE_HOME / "session-rotate-pending.json"


def _bridge() -> tuple[str, str]:
    cfg_path = SURFCORE_HOME / "config.json"
    cfg = {}
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    root = Path(str(cfg.get("qqbotRoot") or "")).expanduser()
    state = root / "state" if root else SURFCORE_HOME / "state"
    token = ""
    port = 3100
    # The bridge process reads <qqbotRoot>/config.json, not the unified
    # .dsh/surfcore/config.json used by the plugin.
    bridge_cfg = {}
    if root:
        try:
            bridge_cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
        except Exception:
            bridge_cfg = {}
    token = str(bridge_cfg.get("consoleToken") or "").strip()
    try:
        port = int(bridge_cfg.get("consolePort") or port)
    except Exception:
        pass
    if not token:
        try:
            token = (state / "console-token").read_text(encoding="utf-8").strip()
        except Exception:
            token = ""
    return f"http://127.0.0.1:{port}", token


def _request(method: str, path: str, body: dict[str, Any] | None = None,
             timeout: int = 10) -> dict[str, Any]:
    base, token = _bridge()
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={
            "content-type": "application/json",
            **({"x-console-token": token} if token else {}),
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def rotate_all(*, reason: str = "sleep") -> dict[str, Any]:
    """Archive every mapped QQ session. Safe to call when bridge is down."""
    try:
        listed = _request("GET", "/api/sessions")
        sessions = listed.get("sessions") if isinstance(listed, dict) else []
        if not isinstance(sessions, list):
            sessions = []
        rotated = []
        for item in sessions:
            key = str((item or {}).get("key") or "")
            if not key:
                continue
            try:
                result = _request("POST", "/api/session/reset", {"key": key})
                rotated.append({"key": key, "ok": bool(result.get("ok")), "result": result})
            except Exception as exc:
                rotated.append({"key": key, "ok": False, "error": str(exc)[:200]})
        out = {"ok": all(x.get("ok") for x in rotated) if rotated else True,
               "reason": reason, "rotated": rotated}
        if not out["ok"]:
            _write_pending(out)
        else:
            try:
                PENDING.unlink(missing_ok=True)
            except OSError:
                pass
        return out
    except Exception as exc:
        out = {"ok": False, "reason": reason, "error": str(exc)[:300], "rotated": []}
        _write_pending(out)
        return out


def _write_pending(payload: dict[str, Any]) -> None:
    try:
        PENDING.parent.mkdir(parents=True, exist_ok=True)
        PENDING.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def rotate_over_budget(*, max_cache_hit: int = 120_000,
                       max_day_tokens: int = 0) -> dict[str, Any]:
    """Optional fixed-program guard: rotate only sessions above a budget.

    Reads the bridge's token ledger; does not infer from the model.
    """
    state_file = SURFCORE_HOME / "token-usage-state.json"
    bridge_root = None
    try:
        cfg = json.loads((SURFCORE_HOME / "config.json").read_text(encoding="utf-8"))
        bridge_root = Path(str(cfg.get("qqbotRoot") or "")).expanduser()
    except Exception:
        pass
    sessions_file = (bridge_root / "state" / "sessions.json") if bridge_root else (SURFCORE_HOME / "state" / "sessions.json")
    try:
        ledger = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"token state unavailable: {exc}", "rotated": []}
    try:
        live = json.loads(sessions_file.read_text(encoding="utf-8")).get("sessions") or {}
    except Exception:
        live = {}
    inverted = {str(sid): key for key, sid in live.items()}
    rows = ledger.get("sessions") if isinstance(ledger, dict) else {}
    if not isinstance(rows, dict):
        rows = {}
    rotated = []
    for sid, info in rows.items():
        key = inverted.get(str(sid))
        if not key:
            continue
        seen = (info or {}).get("seen") or {}
        cache_hit = int((seen.get("cacheHit") or 0))
        day_tokens = int((info or {}).get("dayTokens") or 0)
        if cache_hit <= max_cache_hit and (max_day_tokens <= 0 or day_tokens <= max_day_tokens):
            continue
        try:
            result = _request("POST", "/api/session/reset", {"key": key})
            rotated.append({"key": key, "session_id": sid, "cache_hit": cache_hit,
                            "day_tokens": day_tokens, "result": result})
        except Exception as exc:
            rotated.append({"key": key, "session_id": sid, "ok": False, "error": str(exc)[:200]})
    return {"ok": all(x.get("result", {}).get("ok") for x in rotated) if rotated else True,
            "max_cache_hit": max_cache_hit, "max_day_tokens": max_day_tokens,
            "rotated": rotated}
