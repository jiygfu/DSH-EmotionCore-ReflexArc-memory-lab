#!/usr/bin/env python3
"""Small settings reader/writer for memory-lab.

This is the future settings-page entry point. It does not touch soulcore.db.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "plugins" / "memory-lab" / "config.json"


def path() -> Path:
    return Path(os.environ.get("MEMORY_LAB_CONFIG") or DEFAULT)


def read() -> dict[str, Any]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write(patch: dict[str, Any]) -> dict[str, Any]:
    data = read()
    data.update({k: v for k, v in patch.items() if v is not None})
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def human_review_enabled() -> bool:
    return bool(read().get("humanReview") is True)
