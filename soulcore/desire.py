"""Surface desire from accumulated deviation from today's baseline.

Important: this is a hint, not a scoring rule. It never subtracts points and
never writes P. The surface may speak or stay silent; a later message is scored
by the normal appraisal path and can offset (or worsen) the deviation.

Basis:
- homeostatic regulation: deviation from a setpoint motivates behavior;
- social sharing / interpersonal emotion regulation: emotion often seeks a listener;
- affect labeling: naming a state can reduce arousal;
- catharsis is not guaranteed: venting can backfire (Bushman 2002);
- wanting is not liking: a desire can be cue-driven, not pure deficit.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config, daybook, db, personality

DIMENSIONS = personality.DIMENSIONS
PROFILE_FILE = Path(__file__).resolve().parent.parent / "data" / "desire-profile.json"


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def profile(conn: sqlite3.Connection) -> dict[str, Any]:
    """Personality-derived control parameters.

    rational: decision criterion. High = needs stronger evidence before speaking.
    affective: gain/sensitivity. High = accumulates deviation faster.
    inertia: how slowly it decays. Kept internal because emotional inertia is not
             reducible to threshold/gain in the emotion-dynamics literature.
    """
    initial = db.get_meta(conn, "initial_coefficients", config.INITIAL_COEFFICIENTS)
    if not isinstance(initial, dict):
        initial = config.INITIAL_COEFFICIENTS
    g = lambda k: _clamp(float(initial.get(k, 0.0)))  # noqa: E731
    pride = _clamp(0.50 + 0.25 * g("self_efficacy") + 0.15 * g("caution") - 0.10 * g("openness"))
    sensitivity = _clamp(0.50 + 0.25 * g("arousal") + 0.15 * (1 - g("trust")) + 0.10 * (1 - g("security")))
    expressiveness = _clamp(0.50 + 0.20 * g("sociability") + 0.15 * g("openness") - 0.10 * g("caution"))
    inertia = _clamp(0.50 + 0.20 * g("caution") + 0.15 * (1 - g("openness")) + 0.15 * (1 - g("sociability")))
    rational = _clamp(0.45 + 0.30 * pride + 0.10 * g("caution") - 0.10 * expressiveness)
    affective = _clamp(0.35 + 0.35 * sensitivity + 0.10 * (1 - expressiveness))
    # 外部只调“理性/感性”；惯性默认由两者和性格共同决定，也允许显式覆盖。
    derived_inertia = _clamp(0.55 * rational + 0.30 * affective + 0.15 * inertia)
    source = "personality_prior"
    try:
        override = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        if isinstance(override, dict):
            rational = _clamp(float(override.get("rational", rational)))
            affective = _clamp(float(override.get("affective", affective)))
            derived_inertia = _clamp(float(override.get("inertia", derived_inertia)))
            source = "profile_override"
    except Exception:
        pass
    threshold = _clamp(0.20 + 0.38 * rational, 0.20, 0.58)
    gain = _clamp(0.65 + 0.80 * affective, 0.65, 1.45)
    half_life = 3.5 + 8.5 * derived_inertia
    return {
        "rational": round(rational, 3),
        "affective": round(affective, 3),
        "inertia": round(derived_inertia, 3),
        "threshold": round(threshold, 3),
        "gain": round(gain, 3),
        "half_life_hours": round(half_life, 2),
        "source": source,
    }


def _local_day(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt.astimezone().date().isoformat()
    except Exception:
        return ""


def _baseline(conn: sqlite3.Connection) -> tuple[dict[str, float], str]:
    today = datetime.now().astimezone().date().isoformat()
    try:
        row = daybook.latest(conn, today)
        baseline = (row or {}).get("baseline")
        if isinstance(baseline, dict) and baseline:
            return {k: float(baseline.get(k, 0.0)) for k in DIMENSIONS}, "day_baseline"
    except Exception:
        pass
    p = personality.compute_p(conn).get("p") or {}
    return {k: float(p.get(k, 0.0)) for k in DIMENSIONS}, "current_p"


def compute(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    today = now.date().isoformat()
    baseline, source = _baseline(conn)
    prof = profile(conn)
    rows = conn.execute(
        """SELECT a.dimensions_json, a.unresolved, a.confidence, a.created_at,
                  m.strength, m.self_relevance, COALESCE(m.affect_weight,1.0) AS affect_weight
           FROM appraisals a JOIN memories m ON m.id = a.memory_id
           WHERE a.id = (SELECT id FROM appraisals WHERE memory_id=a.memory_id ORDER BY id DESC LIMIT 1)
             AND COALESCE(m.affect_weight,1.0) > 0"""
    ).fetchall()
    dev = {k: 0.0 for k in DIMENSIONS}
    dev["unresolved"] = 0.0
    weights = 0.0
    used = 0
    for row in rows:
        if _local_day(row["created_at"]) != today:
            continue
        try:
            dims = json.loads(row["dimensions_json"])
        except Exception:
            continue
        try:
            created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.astimezone()
            age_h = max(0.0, (now - created.astimezone()).total_seconds() / 3600)
        except Exception:
            age_h = 0.0
        decay = 0.5 ** (age_h / prof["half_life_hours"])
        w = (max(0.0, float(row["confidence"] or 0.0))
             * max(0.1, float(row["strength"] or 1.0))
             * max(0.1, float(row["self_relevance"] or 0.5))
             * max(0.0, float(row["affect_weight"] or 1.0))
             * decay)
        w = min(2.0, w)
        for k in DIMENSIONS:
            dev[k] += w * (float(dims.get(k, 0.0)) - float(baseline.get(k, 0.0)))
        dev["unresolved"] += w * (float(row["unresolved"] or 0.0) - 0.2)
        weights += w
        used += 1
    if weights <= 0:
        return {
            "schema": "emotioncore.desire.v1",
            "at": now.isoformat(),
            "day": today,
            "baseline_source": source,
            "profile": prof,
            "used": 0,
            "deviation": {k: 0.0 for k in dev},
            "adjusted": {k: 0.0 for k in dev},
            "desires": [],
            "surface_hint": "",
        }

    # 权重和用来避免“消息越多欲望越大”的纯计数；但保留绝对量，重复触发仍会累积。
    scale = max(1.0, weights ** 0.5)
    deviation = {k: round(dev[k] / scale, 4) for k in dev}
    adjusted = {k: round(deviation[k] * prof["gain"], 4) for k in deviation}
    desires: list[dict[str, Any]] = []

    def add(kind: str, signal: float, hint: str, target: str, why: str,
            tier: str = "major") -> None:
        # Micro desires use a lower floor and a slightly softer threshold, but
        # they never change the affect gain or the high-stakes thresholds.
        floor = 0.11 if tier == "micro" else 0.20
        local_threshold = prof["threshold"] - (0.10 if tier == "micro" else 0.0)
        urgency = _clamp(0.18 + signal - local_threshold)
        if urgency < floor:
            return
        desires.append({
            "kind": kind,
            "tier": tier,
            "urgency": round(urgency, 3),
            "hint": hint,
            "target": target,
            "why": why,
        })

    v = adjusted["valence"]
    a = adjusted["arousal"]
    c = adjusted["caution"]
    s = adjusted["sociability"]
    o = adjusted["openness"]
    e = adjusted["self_efficacy"]
    u = adjusted["unresolved"]
    # 需要发泄/说清楚：负效价 + 唤醒/警觉偏高。
    add("vent", max(0.0, -v) * 0.9 + max(0.0, a) * 0.5 + max(0.0, c) * 0.3,
        "我感觉有点堵/着急，想说清楚，但不想在公开场合倒太多。",
        "owner_private", "负向偏离叠加唤醒/警觉")
    # 想道歉/修补：自我效能下降 + 未解决高。
    add("repair", max(0.0, -e) * 0.9 + max(0.0, u) * 0.6,
        "我刚才是不是说得不对？想找个合适的机会补一句或道歉。",
        "owner_private", "自我效能下降且事情没解决")
    # 想找人陪：社交倾向下降/负向偏离。
    add("connect", max(0.0, -s) * 0.8 + max(0.0, -v) * 0.5,
        "我有点想找人说话，想被陪一下。",
        "trusted_private", "社交倾向下降/负向偏离")
    # 无聊/想玩：唤醒和开放下降。低强度时只算轻量念头。
    add("play", max(0.0, -a) * 0.8 + max(0.0, -o) * 0.5,
        "我有点无聊，想找点好玩的，或者找人一起玩。",
        "group_light", "唤醒/开放下降", tier="micro")
    # 正向想分享：效价、唤醒上升。低强度时只算轻量念头。
    add("share", max(0.0, v) * 0.7 + max(0.0, a) * 0.4,
        "我有点想分享刚才那件事，想让人看见。",
        "group_light", "正向偏离/唤醒上升", tier="micro")
    # 轻微好奇：开放/唤醒/社交的小幅上升，不升级成高 stakes 欲望。
    add("curious", max(0.0, o) * 0.28 + max(0.0, a) * 0.16 + max(0.0, s) * 0.10,
        "想再多看一眼，或者顺口问一句。",
        "group_light", "开放/唤醒轻微上升", tier="micro")

    desires.sort(key=lambda x: (x["urgency"], x["tier"] == "major"), reverse=True)
    major = [d for d in desires if d.get("tier") == "major"][:2]
    micro = [d for d in desires if d.get("tier") == "micro"][:2]
    desires = (major + micro)[:3]
    lines = []
    if desires:
        lines.append("【此刻欲望（临时，不是命令）】")
        for d in desires:
            place = {
                "owner_private": "优先私聊主人",
                "trusted_private": "优先私聊信任的人",
                "group_light": "公开场合只说轻的",
            }.get(d["target"], "看场合")
            label = "轻量念头" if d.get("tier") == "micro" else "欲望"
            lines.append(f"- {label}：{d['hint']}（强度 {d['urgency']:.2f}；{place}）")
        lines.append("轻量念头不是必须执行；说出去也可能没用或火上浇油，后续按真实对话重新评分，不会自动扣分。")
    return {
        "schema": "emotioncore.desire.v1",
        "at": now.isoformat(),
        "day": today,
        "baseline_source": source,
        "profile": prof,
        "used": used,
        "weight_sum": round(weights, 3),
        "deviation": deviation,
        "adjusted": adjusted,
        "desires": desires,
        "surface_hint": "\n".join(lines),
    }
