"""Best-effort DeepSeek balance probe.

Reads the existing local DSH credential file; never prints the key.
Only writes data/balance.json (temporary status), not memories/P.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DSH_HOME = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))
CREDENTIALS = DSH_HOME / ".credentials.yaml"
OUT = DATA / "balance.json"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect with the Bearer key attached."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _api_key() -> str:
    key = str(os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if key:
        return key
    try:
        raw = CREDENTIALS.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.search(r"^\s*DEEPSEEK_API_KEY:\s*([^\s#]+)\s*$", raw, re.MULTILINE)
    return m.group(1) if m else ""


def refresh(*, timeout: int = 8) -> dict[str, Any]:
    key = _api_key()
    if not key:
        return {"ok": False, "error": "DEEPSEEK_API_KEY not found"}
    req = urllib.request.Request(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
    infos = payload.get("balance_infos") or []
    if not infos:
        return {"ok": False, "error": "balance_infos empty", "available": payload.get("is_available")}
    info = infos[0]
    try:
        balance = float(info.get("total_balance"))
    except Exception:
        balance = None
    result = {
        "ok": True,
        "balance": balance,
        "currency": str(info.get("currency") or "CNY"),
        "granted": info.get("granted_balance"),
        "topped_up": info.get("topped_up_balance"),
        "available": payload.get("is_available"),
        "at": datetime.now().astimezone().isoformat(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(OUT, 0o600)
    except OSError:
        pass
    return result


def cached() -> dict[str, Any] | None:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return None
