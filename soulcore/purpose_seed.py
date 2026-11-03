"""Export a small affect seed for SurfCore's purpose engine.

The seed uses the day-start baseline (daily_summaries.baseline), not the
long-term cumulative P. If today's baseline has not been captured yet, it
falls back to the current P without changing it.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from . import body_state, daybook, db, personality

DIMENSIONS = personality.DIMENSIONS
SURFCORE_HOME = Path.home() / ".dsh" / "surfcore"
CHARACTERS_DIR = SURFCORE_HOME / "characters"


def active_character() -> dict[str, Any] | None:
    """Find the loaded SurfCore character without hardcoding its random id."""
    role_name = ""
    for role_file in (SURFCORE_HOME / "current-role.json",):
        try:
            role = json.loads(role_file.read_text(encoding="utf-8"))
            role_name = str(role.get("role") or "").strip()
            if role_name:
                break
        except Exception:
            continue
    if not role_name:
        try:
            cfg = json.loads((SURFCORE_HOME / "config.json").read_text(encoding="utf-8"))
            role_file = Path(str(cfg.get("qqbotRoot") or "")).expanduser() / "state" / "current-role.json"
            role = json.loads(role_file.read_text(encoding="utf-8"))
            role_name = str(role.get("role") or "").strip()
        except Exception:
            pass
    candidates = []
    try:
        for p in CHARACTERS_DIR.iterdir():
            meta = p / "character.json"
            if not meta.exists():
                continue
            try:
                obj = json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                continue
            candidates.append({
                "id": str(obj.get("id") or p.name),
                "name": str(obj.get("name") or ""),
                "lastLoadedAt": str(obj.get("lastLoadedAt") or ""),
                "dir": p,
            })
    except Exception:
        return None
    if not candidates:
        return None
    if role_name:
        for c in candidates:
            if c["name"] == role_name:
                return c
    candidates.sort(key=lambda c: c["lastLoadedAt"], reverse=True)
    return candidates[0]


def default_out() -> Path:
    """Prefer the active character's own seed; fallback to bridge state."""
    char = active_character()
    if char:
        return char["dir"] / "soulcore-purpose.json"
    try:
        cfg = json.loads((SURFCORE_HOME / "config.json").read_text(encoding="utf-8"))
        root = Path(str(cfg.get("qqbotRoot") or "")).expanduser()
        if root:
            return root / "state" / "soulcore-purpose.json"
    except Exception:
        pass
    return SURFCORE_HOME / "soulcore-purpose.json"


DEFAULT_OUT = default_out()


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _drives(p: dict[str, Any], *, unresolved: float = 0.2) -> dict[str, float]:
    g = lambda k: _clamp(float(p.get(k, 0.0)))  # noqa: E731
    pos = max(0.0, float(p.get("valence", 0.0)))
    neg = max(0.0, -float(p.get("valence", 0.0)))
    return {
        "play": _clamp(0.08 + 0.30 * g("openness") + 0.25 * g("arousal") + 0.15 * pos),
        "learn": _clamp(0.10 + 0.35 * g("openness") + 0.20 * g("self_efficacy") + 0.15 * (1 - g("caution"))),
        "install": _clamp(0.08 + 0.25 * g("openness") + 0.20 * g("self_efficacy") + 0.15 * (1 - g("caution"))),
        "connect": _clamp(0.12 + 0.32 * g("sociability") + 0.20 * (1 - g("security")) + 0.15 * (1 - g("trust")) + 0.18 * neg),
        "care": _clamp(0.10 + 0.30 * g("trust") + 0.20 * g("caution") + 0.20 * (1 - g("security")) + 0.10 * neg),
        "share": _clamp(0.10 + 0.30 * pos + 0.25 * g("arousal") + 0.20 * g("sociability")),
        "identity": _clamp(0.08 + 0.30 * g("self_efficacy") + 0.25 * _clamp(unresolved) + 0.15 * g("openness")),
        "create": _clamp(0.05 + 0.25 * g("openness") + 0.20 * g("self_efficacy") + 0.15 * g("arousal")),
        "consume": _clamp(0.05 + 0.25 * g("arousal") + 0.20 * pos + 0.10 * g("openness")),
    }


def _emotion(p: dict[str, Any], drives: dict[str, float], unresolved: float) -> str:
    g = lambda k: _clamp(float(p.get(k, 0.0)))  # noqa: E731
    if drives["connect"] >= 0.55 and float(p.get("valence", 0.0)) < -0.05:
        return "lonely"
    if g("caution") >= 0.58 and float(p.get("valence", 0.0)) < 0.0:
        return "worried"
    if g("self_efficacy") >= 0.62 and float(p.get("valence", 0.0)) > 0.05:
        return "proud"
    if g("trust") >= 0.55 and float(p.get("valence", 0.0)) > 0.1:
        return "affectionate"
    if g("arousal") < 0.32 and unresolved < 0.4:
        return "bored"
    return "content"


def _body_context() -> dict[str, Any]:
    """Read-only body pressure. Never writes P/memories."""
    try:
        snap = body_state.snapshot(write=False)
    except Exception:
        return {}
    states = snap.get("states") or {}
    raw = snap.get("raw") or {}
    return {
        "states": {k: round(_clamp(float(states.get(k, 0.0))), 4) for k in
                   ("stress", "fatigue", "cognitive_load", "sleepiness", "resource_need", "thermal_load", "recovery")},
        "balance": raw.get("balance"),
        "temp_c": raw.get("temp_c"),
        "temporary_only": True,
    }


def _apply_body(drives: dict[str, float], pending: float, body: dict[str, Any]) -> tuple[dict[str, float], float]:
    """Short-lived modulation only; does not touch P or memory."""
    s = body.get("states") or {}
    fatigue = max(float(s.get("fatigue", 0.0)), float(s.get("sleepiness", 0.0)))
    load = max(float(s.get("stress", 0.0)), float(s.get("cognitive_load", 0.0)), float(s.get("thermal_load", 0.0)))
    resource = float(s.get("resource_need", 0.0))
    recovery = float(s.get("recovery", 0.0))
    damp = 1.0
    if fatigue > 0.45:
        damp *= 1.0 - 0.22 * ((fatigue - 0.45) / 0.55)
    if load > 0.45:
        damp *= 1.0 - 0.18 * ((load - 0.45) / 0.55)
    if resource > 0.45:
        damp *= 1.0 - 0.25 * ((resource - 0.45) / 0.55)
    damp = max(0.45, min(1.05, damp + 0.03 * recovery))
    out = {}
    for k, v in drives.items():
        factor = damp
        if k in ("share", "play", "connect"):
            factor *= 1.0 - 0.15 * max(fatigue, load)
        if k == "consume":
            factor *= 1.0 - 0.30 * resource
        out[k] = round(_clamp(float(v) * factor), 4)
    pending = _clamp(float(pending) * (0.55 + 0.45 * damp))
    return out, pending


def build(conn, *, day: str | None = None) -> dict[str, Any]:
    try:
        row = daybook.ensure_day_baseline(conn, day=day)
        p = json.loads(row["baseline_json"] or "{}")
        source = "day_baseline"
    except Exception:
        p = {}
        source = "current_p"
    if not p:
        p = personality.compute_p(conn).get("p") or {}
        source = "current_p"
    unresolved = 0.2
    try:
        r = conn.execute(
            """SELECT AVG(a.unresolved) AS u FROM appraisals a
               JOIN memories m ON m.id=a.memory_id
               WHERE COALESCE(m.affect_weight,1.0) > 0"""
        ).fetchone()
        if r and r["u"] is not None:
            unresolved = _clamp(float(r["u"]))
    except Exception:
        pass
    drives = _drives(p, unresolved=unresolved)
    emotion = _emotion(p, drives, unresolved)
    body = _body_context()
    pending = _clamp(0.15 + 0.45 * unresolved + 0.25 * drives["connect"] + 0.10 * max(0.0, -float(p.get("valence", 0.0))))
    drives, pending = _apply_body(drives, pending, body)
    urgency = _clamp(max(drives.values()) * 0.75 + unresolved * 0.25)
    char = active_character()
    return {
        "schema": "soulcore.purpose.v1",
        "at": datetime.now().astimezone().isoformat(),
        "day_key": (day or datetime.now().astimezone().date().isoformat()),
        "character_id": char["id"] if char else "",
        "p_source": source,
        "p": {k: round(float(p.get(k, 0.0)), 4) for k in DIMENSIONS},
        "drives": {k: round(v, 4) for k, v in drives.items()},
        "emotion": emotion,
        "unresolved": round(unresolved, 4),
        "urgency": round(urgency, 4),
        "pending_chance": round(pending, 4),
        "body": body,
        "confidence": 0.7,
    }


def write(conn, *, out: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    data = build(conn)
    target = Path(out).expanduser() if out else default_out()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".soulcore-purpose-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, target)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
    return {"ok": True, "path": str(target), **data}
