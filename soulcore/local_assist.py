"""Optional local-model polish for episode cards.

This is deliberately off the critical path:
- disabled by default;
- only rewrites the L1 summary text;
- raw memories are untouched;
- any failure keeps the deterministic extractive summary.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent / "data"
DEFAULT = {"enabled": False, "model": "", "base_url": "http://127.0.0.1:11434", "timeout_s": 8}


def config() -> dict[str, Any]:
    out = dict(DEFAULT)
    for file in (DATA / "episode-summary.json", DATA / "appraisal-config.json"):
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        if file.name == "episode-summary.json":
            for k in out:
                if raw.get(k) is not None:
                    out[k] = raw[k]
        elif not out.get("model"):
            out["model"] = str(raw.get("model") or "")
            out["base_url"] = str(raw.get("base_url") or out["base_url"])
    return out


def summarize(text: str, *, timeout: float | None = None) -> str | None:
    cfg = config()
    if cfg.get("enabled") is not True or not cfg.get("model"):
        return None
    prompt = (
        "把下面这段事件摘要压缩成 2~4 句中文，保留人物、起因、结果和未解决点；"
        "不要编造原文没有的细节，不要加评价。只输出摘要：\n\n" + str(text)[:4000]
    )
    body = json.dumps({
        "model": cfg["model"],
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 180},
    }).encode("utf-8")
    req = urllib.request.Request(
        str(cfg["base_url"]).rstrip("/") + "/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout or cfg.get("timeout_s") or 8)) as res:
            data = json.loads(res.read().decode("utf-8", "replace"))
        out = str(data.get("response") or "").strip()
        return out[:1000] or None
    except Exception:
        return None


def polish_day(conn, *, day: str) -> dict[str, Any]:
    rows = conn.execute("SELECT id, summary FROM episodes WHERE day=?", (day,)).fetchall()
    changed = 0
    for row in rows:
        out = summarize(row["summary"])
        if not out or out == row["summary"]:
            continue
        conn.execute("UPDATE episodes SET summary=?, updated_at=datetime('now') WHERE id=?", (out, row["id"]))
        changed += 1
    conn.commit()
    return {"ok": True, "day": day, "episodes": len(rows), "polished": changed}
