"""Day-end / shutdown consolidation for Phase 1.

Rule:
  - low-importance, low-unresolved, low-arousal events keep their text,
    but their affect_weight becomes 0;
  - important / "上心" events keep affect_weight 1 and remain in the affect
    aggregate;
  - no memory is deleted in Phase 1.

This is an engineering approximation of "sleep keeps what matters".
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime
from typing import Any

from . import config, db


def _impact(memory: sqlite3.Row, appraisal: sqlite3.Row) -> float:
    """0..1 magnitude of a memory's affective impact.

    This is the value whose daily average is recorded before low-importance
    events are cleaned. It is not a personality change.
    """
    try:
        d = json.loads(appraisal["dimensions_json"])
    except Exception:
        d = {}
    valence = abs(float(d.get("valence", 0.0)))
    caution = float(d.get("caution", 0.0))
    arousal = float(d.get("arousal", 0.0))
    security = float(d.get("security", 0.5))
    unresolved = float(appraisal["unresolved"] or 0.0)
    confidence = float(appraisal["confidence"] or 0.0)
    self_rel = float(memory["self_relevance"] or 0.5)
    raw = (
        0.30 * valence
        + 0.25 * caution
        + 0.20 * unresolved
        + 0.15 * arousal
        + 0.10 * (1.0 - security)
    )
    return round(max(0.0, min(1.0, raw * (0.5 + 0.5 * confidence) * (0.5 + 0.5 * self_rel))), 4)


def _important(memory: sqlite3.Row, appraisal: sqlite3.Row) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    try:
        dims = json.loads(appraisal["dimensions_json"])
    except Exception:
        dims = {}
    try:
        raw = json.loads(memory["raw_json"] or "{}")
    except Exception:
        raw = {}
    c = config.CONSOLIDATION
    if bool(appraisal["has_impact"]):
        reasons.append("has_impact")
    if bool(raw.get("pinned")):
        reasons.append("pinned")
    if float(memory["importance"] or 0) >= c["importance_min"]:
        reasons.append("importance")
    if float(appraisal["unresolved"] or 0) >= c["unresolved_min"]:
        reasons.append("unresolved")
    if abs(float(dims.get("valence", 0))) >= c["abs_valence_min"]:
        reasons.append("strong_valence")
    if float(dims.get("arousal", 0)) >= c["arousal_min"]:
        reasons.append("high_arousal")
    return bool(reasons), reasons


def run(
    conn: sqlite3.Connection,
    *,
    mode: str = "day_end",
    dry_run: bool = False,
) -> dict[str, Any]:
    if mode not in set(config.CONSOLIDATION.get("modes", ["day_end"])):
        raise ValueError(f"unknown consolidation mode: {mode}")
    c = config.CONSOLIDATION
    rows = conn.execute(
        """SELECT m.*, a.id AS appraisal_id, a.dimensions_json, a.unresolved,
                  a.confidence, a.has_impact, a.evidence
           FROM memories m
           JOIN appraisals a ON a.id = (
               SELECT id FROM appraisals WHERE memory_id = m.id ORDER BY id DESC LIMIT 1
           )
           WHERE COALESCE(m.consolidation_state, 'none') = 'none'
           ORDER BY m.id"""
    ).fetchall()
    kept = 0
    ignored = 0
    skipped = 0
    details: list[dict[str, Any]] = []
    unimportant: list[dict[str, Any]] = []
    now = db.utcnow()
    day_key = datetime.now().astimezone().date().isoformat()

    for row in rows:
        important, reasons = _important(row, row)
        impact = _impact(row, row)
        if important:
            kept += 1
            state = "kept"
            weight = 1.0
        else:
            ignored += 1
            state = "ignored"
            weight = 0.0
            unimportant.append({"id": row["id"], "impact": impact})
        details.append({
            "id": row["id"],
            "state": state,
            "weight": weight,
            "impact": impact,
            "reasons": reasons,
        })
        if not dry_run:
            conn.execute(
                """UPDATE memories
                   SET consolidation_state=?, affect_weight=?, consolidated_at=?, updated_at=?
                   WHERE id=?""",
                (state, weight, now, now, row["id"]),
            )

    # Record the ambient impact of "unimportant" events BEFORE they are cleaned.
    # This is a signal about the surrounding tone, not a personality change.
    ambient_sum = round(sum(x["impact"] for x in unimportant), 4)
    ambient_mean = round(ambient_sum / len(unimportant), 4) if unimportant else 0.0
    past = conn.execute(
        """SELECT ambient_mean FROM consolidation_runs
           WHERE ambient_count > 0 AND ambient_mean IS NOT NULL
           ORDER BY id DESC LIMIT 14"""
    ).fetchall()
    past_vals = [float(r["ambient_mean"]) for r in past]
    baseline = round(statistics.mean(past_vals), 4) if past_vals else None
    zscore = None
    if len(past_vals) >= 3:
        sd = statistics.pstdev(past_vals)
        if sd > 0.02 and baseline is not None:
            zscore = round((ambient_mean - baseline) / sd, 3)
    flagged = False
    reason = ""
    if len(unimportant) >= 3:
        if ambient_mean >= float(c["ambient_mean_min"]):
            flagged = True
            reason = "daily_mean_high"
        elif zscore is not None and zscore >= 2.0:
            flagged = True
            reason = "above_baseline_2sd"
    ambient = {
        "day_key": day_key,
        "count": len(unimportant),
        "sum": ambient_sum,
        "mean": ambient_mean,
        "baseline": baseline,
        "zscore": zscore,
        "flagged": flagged,
        "reason": reason,
    }

    if not dry_run:
        conn.execute(
            """INSERT INTO ambient_pressures
               (day_key, mean_impact, sum_impact, count, baseline_mean, zscore,
                flagged, reason, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (day_key, ambient_mean, ambient_sum, len(unimportant), baseline,
             zscore, 1 if flagged else 0, reason,
             json.dumps(unimportant, ensure_ascii=False), now),
        )
        conn.execute(
            """INSERT INTO consolidation_runs
               (mode, day_key, kept, ignored, skipped,
                ambient_mean, ambient_sum, ambient_count, ambient_baseline,
                ambient_z, ambient_flagged, ambient_reason, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mode, day_key, kept, ignored, skipped,
             ambient_mean, ambient_sum, len(unimportant), baseline,
             zscore, 1 if flagged else 0, reason,
             json.dumps(details, ensure_ascii=False), now),
        )
        conn.commit()
    return {
        "mode": mode,
        "dry_run": dry_run,
        "scanned": len(rows),
        "kept": kept,
        "ignored": ignored,
        "skipped": skipped,
        "ambient": ambient,
        "details": details,
    }

