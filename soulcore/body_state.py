"""Ephemeral body state for surface dialogue.

Hard boundary:
- never writes P, appraisals, memories, daily summaries, or purpose drives;
- only writes a short-TTL body-state.json + a prompt hint;
- missing psutil / balance widget is a normal fallback, not an error.

The device is a metaphor for the pet's body, not a medical model.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover - public installs may omit it
    psutil = None

DATA = Path(__file__).resolve().parent.parent / "data"
STATE_FILE = DATA / "body-state.json"
DSH_HOME = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))
BALANCE_CANDIDATES = (
    Path.home() / ".dshw-usage.json",
    DSH_HOME / ".dshw-usage.json",
    DSH_HOME / "profiles" / "web" / ".dshw-usage.json",
    DSH_HOME / "profiles" / "desktop" / ".dshw-usage.json",
)

TTL_SEC = 300
NIGHT_START = 22
NIGHT_END = 7


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _widget_usage() -> float | None:
    files = [p for p in BALANCE_CANDIDATES if p.exists()]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    try:
        raw = json.loads(files[0].read_text(encoding="utf-8"))
        usage = raw.get("todayUsage")
        if usage:
            return float(usage)
        return sum(float(e.get("cost") or 0.0) for e in (raw.get("events") or []))
    except Exception:
        return None


def _read_balance() -> dict[str, Any] | None:
    # A direct API probe is preferred: it works even when the widget has not
    # been opened in the browser yet.
    try:
        from . import balance as balance_probe
        cached = balance_probe.cached()
        if cached and cached.get("balance") is not None:
            return {
                "balance": float(cached.get("balance")),
                "today_usage": cached.get("today_usage") if cached.get("today_usage") is not None else _widget_usage(),
                "currency": cached.get("currency") or "CNY",
                "path": str(balance_probe.OUT),
            }
    except Exception:
        pass
    files = [p for p in BALANCE_CANDIDATES if p.exists()]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    try:
        raw = json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    balance = raw.get("lastBalance")
    usage = raw.get("todayUsage")
    if not usage:
        try:
            usage = sum(float(e.get("cost") or 0.0) for e in (raw.get("events") or []))
        except Exception:
            usage = None
    currency = "CNY"
    try:
        accounting = raw.get("accounting") or {}
        active = accounting.get("active") or ""
        books = accounting.get("books") or {}
        book = books.get(active) or next(iter(books.values()), {}) if books else {}
        currency = str(book.get("currency") or currency)
    except Exception:
        pass
    try:
        balance = float(balance) if balance is not None else None
    except Exception:
        balance = None
    try:
        usage = float(usage) if usage is not None else None
    except Exception:
        usage = None
    return {
        "balance": balance,
        "today_usage": usage,
        "currency": currency,
        "path": str(files[0]),
    }


def _night_factor(now: datetime) -> float:
    hour = now.hour + now.minute / 60
    if hour >= NIGHT_START:
        return _clamp((hour - NIGHT_START) / 4.0 + 0.5)
    if hour < NIGHT_END:
        return _clamp(1.0 - hour / NIGHT_END)
    return 0.0


def _surface_hint(states: dict[str, float], raw: dict[str, Any]) -> str:
    bits = []
    if states["stress"] >= 0.6:
        bits.append("负载偏高，有点紧绷")
    if states["fatigue"] >= 0.6:
        bits.append("连续运转/电量偏低，有点累")
    if states["cognitive_load"] >= 0.65:
        bits.append("内存/信息负载偏高")
    if states["sleepiness"] >= 0.6:
        bits.append("夜深了，有点困")
    if states["resource_need"] >= 0.55:
        bits.append("资源余额偏低，花起来会谨慎")
    if states["recovery"] >= 0.6 and not bits:
        bits.append("刚充上电/负载低，状态在恢复")
    if not bits:
        return ""
    balance = raw.get("balance")
    extra = ""
    if balance is not None:
        extra = f"（API 余额约 {balance:.2f}）"
    return (
        "【此刻身体状态（临时，只影响这一轮语气）】"
        + "；".join(bits) + extra
        + "。不要把它写进记忆、P、关系或长期人格；也不要把它说成真实的人类疾病。"
    )


def snapshot(*, write: bool = True, now: float | None = None) -> dict[str, Any]:
    ts = now if now is not None else time.time()
    dt = datetime.fromtimestamp(ts).astimezone()
    raw: dict[str, Any] = {
        "cpu_pct": None, "mem_pct": None, "disk_pct": None,
        "battery_pct": None, "power_plugged": None,
        "uptime_sec": None, "temp_c": None,
        "balance": None, "today_usage": None, "currency": None,
    }
    if psutil is not None:
        try:
            raw["cpu_pct"] = round(float(psutil.cpu_percent(interval=0.15)), 1)
            mem = psutil.virtual_memory()
            raw["mem_pct"] = round(float(mem.percent), 1)
            try:
                raw["disk_pct"] = round(float(psutil.disk_usage(os.path.abspath(os.sep)).percent), 1)
            except Exception:
                pass
            try:
                bat = psutil.sensors_battery()
                if bat is not None:
                    raw["battery_pct"] = round(float(bat.percent), 1)
                    raw["power_plugged"] = bool(bat.power_plugged)
            except Exception:
                pass
            raw["uptime_sec"] = round(max(0.0, ts - float(psutil.boot_time())), 0)
            try:
                temps = psutil.sensors_temperatures() or {}
                values = [item.current for group in temps.values() for item in group if getattr(item, "current", None) is not None]
                if values:
                    raw["temp_c"] = round(max(values), 1)
            except Exception:
                pass
        except Exception:
            pass
    bal = _read_balance()
    if bal:
        raw.update({k: bal.get(k) for k in ("balance", "today_usage", "currency")})

    cpu = _clamp((raw["cpu_pct"] or 0) / 100)
    mem = _clamp((raw["mem_pct"] or 0) / 100)
    disk = _clamp((raw["disk_pct"] or 0) / 100)
    hours = _clamp((raw["uptime_sec"] or 0) / (24 * 3600), 0, 1)
    battery_pct = raw["battery_pct"]
    battery = _clamp((battery_pct if battery_pct is not None else 100.0) / 100)
    plugged = bool(raw["power_plugged"])
    low_battery = 0.0 if plugged else _clamp(1.0 - battery / 0.5)
    night = _night_factor(dt)
    balance = raw["balance"]
    resource_need = 0.0
    if balance is not None:
        # 5 元以下明显紧张，50 元以上视为充足；这不是实际账户建议。
        resource_need = _clamp(1.0 - (float(balance) - 5.0) / 45.0)
    thermal = 0.0
    if raw["temp_c"] is not None:
        thermal = _clamp((float(raw["temp_c"]) - 55.0) / 35.0)

    states = {
        "stress": round(_clamp(0.55 * cpu + 0.20 * mem + 0.15 * hours + 0.10 * thermal), 3),
        "arousal": round(_clamp(0.70 * cpu + 0.20 * thermal + 0.10 * night), 3),
        "fatigue": round(_clamp(0.35 * low_battery + 0.35 * hours + 0.20 * mem + 0.10 * disk), 3),
        "cognitive_load": round(_clamp(0.60 * mem + 0.25 * cpu + 0.15 * disk), 3),
        "sleepiness": round(_clamp(0.70 * night + 0.30 * hours), 3),
        "resource_need": round(resource_need, 3),
        "thermal_load": round(thermal, 3),
        "recovery": round(_clamp((0.60 if plugged else 0.0) + 0.25 * (1 - cpu)), 3),
    }
    out = {
        "schema": "emotioncore.body.v1",
        "at": dt.isoformat(),
        "expires_at": datetime.fromtimestamp(ts + TTL_SEC).astimezone().isoformat(),
        "ttl_sec": TTL_SEC,
        "temporary_only": True,
        "not_for_persistence": True,
        "raw": raw,
        "states": states,
        "surface_hint": _surface_hint(states, raw),
    }
    if write:
        DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".body-state-", dir=str(DATA))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(out, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, STATE_FILE)
        finally:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass
    return out


def read_hint() -> str:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not data.get("temporary_only"):
            return ""
        expires = datetime.fromisoformat(str(data.get("expires_at")))
        if datetime.now().astimezone() > expires:
            return ""
        return str(data.get("surface_hint") or "")
    except Exception:
        return ""
