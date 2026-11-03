"""耐心（M6）：负载与恢复的动态平衡。

不是第 9 个情绪维度，而是现有信号的合成视图：
  load   = 0.45×未完成事件负荷 + 0.35×睡眠债 + 0.20×近 24h 负向情绪
  relief = 0.50×近 24h 正向情绪 + 0.30×共鸣/学习 + 0.20×刚休息过
  patience = clamp(0.65 + relief − load, 0.15, 1.0)

低耐心不是"变冷淡"，是"想清账"：拒绝新的"回头聊"，更想把到期的事了结。
只写一个 json 给桥接读；不碰 P、不碰记忆。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SURFCORE_HOME = Path.home() / ".dsh" / "surfcore"
OUT = SURFCORE_HOME / "patience.json"
LOOPS = SURFCORE_HOME / "loops.jsonl"
DAY = 86_400
# 基础值：什么都没发生时就该是"还好"，不是"很累"。
BASE = 0.65


def clamp01(v: float) -> float:
    try:
        n = float(v)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, n))


def compute(parts: dict[str, float]) -> dict[str, Any]:
    load = (
        0.45 * clamp01(parts.get("pending_load", 0))
        + 0.35 * clamp01(parts.get("sleep_debt", 0))
        + 0.20 * clamp01(parts.get("negative_affect", 0))
    )
    relief = (
        0.50 * clamp01(parts.get("positive_affect", 0))
        + 0.30 * clamp01(parts.get("resonance", 0))
        + 0.20 * clamp01(parts.get("rest_done", 0))
    )
    patience = max(0.15, min(1.0, BASE + relief - load))
    return {
        "patience": round(patience, 3),
        "load": round(load, 3),
        "relief": round(relief, 3),
    }


def _load_loops(path: Path = LOOPS) -> list[dict[str, Any]]:
    """只读 loops.jsonl（桥接是唯一写者）。坏行跳过。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: dict[str, dict[str, Any]] = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("op") == "upsert" and rec.get("loop", {}).get("id"):
            out[rec["loop"]["id"]] = rec["loop"]
        elif rec.get("op") == "event" and rec.get("id") in out:
            loop = out[rec["id"]]
            if rec.get("type") in ("close", "drop"):
                loop["status"] = "done" if rec["type"] == "close" else "dropped"
            elif rec.get("type") == "archive":
                loop["status"] = "archived"
    return list(out.values())


def pending_load(loops: list[dict[str, Any]], now_ms: int) -> float:
    """有时限且已到期的权重更高；5 条活跃就满负荷。"""
    score = 0.0
    for loop in loops:
        if loop.get("status") not in ("open", "paused", "waiting"):
            continue
        imp = float(loop.get("importance") or 0.5)
        anchor = loop.get("anchor_at")
        due = 1.5 if anchor and int(anchor) <= now_ms else 1.0
        score += imp * due
    return min(1.0, score / 5.0)


def _last_sleep_at(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT at FROM sleep_runs WHERE reason IN ('sleep','daily') ORDER BY at DESC LIMIT 1").fetchone()
        if not row:
            return 0
        # sleep_runs.at 是本地时间字符串
        import datetime as _dt
        text = str(row["at"] if isinstance(row, sqlite3.Row) else row[0])
        return int(_dt.datetime.fromisoformat(text).timestamp() * 1000)
    except Exception:
        return 0


def _affect_parts(conn: sqlite3.Connection, now_ms: int) -> dict[str, float]:
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime((now_ms - DAY) / 1000))
    try:
        rows = conn.execute(
            "SELECT dimensions_json FROM appraisals WHERE created_at >= ? LIMIT 500", (since,)
        ).fetchall()
    except Exception:
        return {"positive_affect": 0.0, "negative_affect": 0.0, "resonance": 0.0}
    pos = neg = 0.0
    res = 0.0
    n = 0
    for row in rows:
        try:
            dims = json.loads(row[0])
        except Exception:
            continue
        n += 1
        v = float(dims.get("valence", 0) or 0)
        if v > 0:
            pos += v
        else:
            neg += -v
        if float(dims.get("openness", 0) or 0) > 0.6:
            res += 1
    if n == 0:
        return {"positive_affect": 0.0, "negative_affect": 0.0, "resonance": 0.0}
    return {
        "positive_affect": clamp01(pos / n),
        "negative_affect": clamp01(neg / n),
        "resonance": clamp01(res / n),
    }


def collect(conn: sqlite3.Connection, *, now_ms: int | None = None, loops_path: Path = LOOPS) -> dict[str, Any]:
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    loops = _load_loops(loops_path)
    last_sleep = _last_sleep_at(conn)
    sleep_debt = 0.0
    rest_done = 0.0
    if last_sleep:
        hours = max(0.0, (now_ms - last_sleep) / 3_600_000)
        sleep_debt = clamp01(hours / 24)
        rest_done = 1.0 if hours <= 8 else 0.0
    parts = {
        "pending_load": pending_load(loops, now_ms),
        "sleep_debt": sleep_debt,
        "rest_done": rest_done,
        **_affect_parts(conn, now_ms),
    }
    result = compute(parts)
    return {**result, "parts": {k: round(v, 3) for k, v in parts.items()}, "at": now_ms}


def write(conn: sqlite3.Connection, *, out: Path = OUT) -> dict[str, Any]:
    data = collect(conn)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(out)
    except Exception:
        pass
    return data
