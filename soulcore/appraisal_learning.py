"""Induce deterministic appraisal patterns from local-model examples.

Safety model:
  shadow  -> the model still runs; the pattern prediction is recorded and compared
  auto    -> a pattern that passes similarity/support/variance gates replaces the model

Only model-produced appraisals become learning examples. Pattern-produced rows are
excluded, so the code path cannot reinforce its own output.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from typing import Any

from . import db

DIMENSIONS = (
    "security", "trust", "self_efficacy", "caution",
    "sociability", "openness", "valence", "arousal",
)

_STOP = {
    "这个", "那个", "就是", "什么", "怎么", "可以", "不是", "没有", "还是",
    "已经", "我们", "你们", "他们", "自己", "现在", "今天", "明天", "昨天",
    "然后", "因为", "所以", "一个", "一下", "真的", "觉得", "知道", "时候",
}


def extract(text: str, limit: int = 80) -> dict[str, float]:
    s = re.sub(r"\s+", "", str(text or "")).lower()
    counts: dict[str, int] = {}
    for segment in re.findall(r"[\u4e00-\u9fa5]+|[a-z0-9_]+", s):
        if re.search(r"[\u4e00-\u9fa5]", segment):
            for n in (2, 3):
                for i in range(0, max(0, len(segment) - n + 1)):
                    tok = segment[i:i + n]
                    if tok in _STOP:
                        continue
                    counts[tok] = counts.get(tok, 0) + 1
        elif len(segment) >= 3:
            counts[segment] = counts.get(segment, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return {tok: round(1.0 + math.log1p(n), 4) for tok, n in top}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _norm(features: dict[str, float]) -> dict[str, float]:
    n = math.sqrt(sum(v * v for v in features.values()))
    return {k: round(v / n, 6) for k, v in features.items()} if n else {}


def ensure_policy(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM appraisal_policy WHERE id=1").fetchone()
    if not row:
        conn.execute(
            """INSERT INTO appraisal_policy
               (id, mode, min_similarity, min_support, max_variance, updated_at)
               VALUES (1, 'shadow', 0.55, 2, 0.08, ?)""",
            (db.utcnow(),),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM appraisal_policy WHERE id=1").fetchone()
    return dict(row)


def _model_examples(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT a.id, a.memory_id, a.dimensions_json, a.feature_json,
                  a.unresolved, a.confidence, a.has_impact, m.text
           FROM appraisals a JOIN memories m ON m.id = a.memory_id
           WHERE a.id = (
               SELECT id FROM appraisals WHERE memory_id = a.memory_id ORDER BY id DESC LIMIT 1
           )
             AND a.appraiser_id LIKE 'ollama:%'
           ORDER BY a.id"""
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            dims = json.loads(row["dimensions_json"])
            feats = json.loads(row["feature_json"] or "null")
        except Exception:
            continue
        if not isinstance(dims, dict):
            continue
        if not isinstance(feats, dict) or not feats:
            feats = extract(row["text"])
        if not feats:
            continue
        out.append({
            "memory_id": row["memory_id"],
            "features": _norm(feats),
            "dims": {k: float(dims.get(k, 0.0)) for k in DIMENSIONS},
            "unresolved": float(row["unresolved"] or 0.0),
            "confidence": float(row["confidence"] or 0.0),
            "has_impact": bool(row["has_impact"]),
        })
    return out


def _merge(cluster: dict[str, Any], ex: dict[str, Any]) -> None:
    n = cluster["count"]
    nn = n + 1
    for k, v in ex["features"].items():
        cluster["centroid"][k] = cluster["centroid"].get(k, 0.0) + v
    cluster["centroid"] = _norm(cluster["centroid"])
    cluster["mean"] = {
        k: round((cluster["mean"].get(k, 0.0) * n + ex["dims"][k]) / nn, 4)
        for k in DIMENSIONS
    }
    cluster["m2"] = {
        k: cluster["m2"].get(k, 0.0) + (ex["dims"][k] - cluster["mean"][k]) ** 2
        for k in DIMENSIONS
    }
    cluster["unresolved"] = round((cluster["unresolved"] * n + ex["unresolved"]) / nn, 4)
    cluster["confidence"] = round((cluster["confidence"] * n + ex["confidence"]) / nn, 4)
    cluster["impact"] = (cluster["impact"] * n + (1 if ex["has_impact"] else 0)) / nn
    cluster["count"] = nn
    cluster["samples"].append(ex["memory_id"])


def learn(conn: sqlite3.Connection, *, similarity: float = 0.4) -> dict[str, Any]:
    examples = _model_examples(conn)
    # Drop one-off n-grams: with a tiny corpus they only create singleton patterns.
    df: dict[str, int] = {}
    for ex in examples:
        for token in ex["features"]:
            df[token] = df.get(token, 0) + 1
    shared = {token for token, count in df.items() if count >= 2}
    filtered = []
    for ex in examples:
        features = {k: v for k, v in ex["features"].items() if k in shared}
        if not features:
            continue
        filtered.append({**ex, "features": _norm(features)})
    examples = filtered
    clusters: list[dict[str, Any]] = []
    for ex in examples:
        best = None
        best_sim = 0.0
        for cluster in clusters:
            sim = cosine(ex["features"], cluster["centroid"])
            if sim > best_sim:
                best, best_sim = cluster, sim
        if best is not None and best_sim >= similarity:
            _merge(best, ex)
        else:
            clusters.append({
                "centroid": dict(ex["features"]),
                "mean": dict(ex["dims"]),
                "m2": {k: 0.0 for k in DIMENSIONS},
                "unresolved": ex["unresolved"],
                "confidence": ex["confidence"],
                "impact": 1.0 if ex["has_impact"] else 0.0,
                "count": 1,
                "samples": [ex["memory_id"]],
            })
    now = db.utcnow()
    conn.execute("DELETE FROM appraisal_patterns")
    for i, c in enumerate(sorted(clusters, key=lambda x: -x["count"])):
        pid = "pat_" + hashlib.sha1(
            "|".join(sorted(c["centroid"])[:12]).encode("utf-8")
        ).hexdigest()[:12]
        variance = {
            k: round(c["m2"].get(k, 0.0) / max(1, c["count"] - 1), 6)
            for k in DIMENSIONS
        }
        conn.execute(
            """INSERT OR REPLACE INTO appraisal_patterns
               (id, centroid_json, mean_json, variance_json, count, impact_rate,
                confidence, sample_ids_json, tokens_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, json.dumps(c["centroid"], ensure_ascii=False),
             json.dumps({**c["mean"], "_unresolved": c["unresolved"]}, ensure_ascii=False),
             json.dumps(variance, ensure_ascii=False), c["count"],
             round(c["impact"], 4), round(c["confidence"], 4),
             json.dumps(c["samples"], ensure_ascii=False),
             json.dumps(sorted(c["centroid"], key=lambda k: -c["centroid"][k])[:8], ensure_ascii=False),
             now, now),
        )
    conn.commit()
    return {"examples": len(examples), "patterns": len(clusters)}


def predict(conn: sqlite3.Connection, text: str) -> dict[str, Any] | None:
    policy = ensure_policy(conn)
    rows = conn.execute("SELECT * FROM appraisal_patterns").fetchall()
    vocab: set[str] = set()
    for row in rows:
        try:
            vocab.update(json.loads(row["centroid_json"]).keys())
        except Exception:
            pass
    feats = {k: v for k, v in extract(text).items() if k in vocab}
    feats = _norm(feats)
    if not feats:
        return None
    best = None
    best_sim = 0.0
    for row in rows:
        try:
            centroid = json.loads(row["centroid_json"])
            mean = json.loads(row["mean_json"])
            variance = json.loads(row["variance_json"] or "{}")
        except Exception:
            continue
        sim = cosine(feats, centroid)
        if sim <= best_sim:
            continue
        count = int(row["count"] or 0)
        max_var = max((float(variance.get(k, 0.0)) for k in DIMENSIONS), default=1.0)
        if count < int(policy["min_support"]):
            continue
        if sim < float(policy["min_similarity"]):
            continue
        if max_var > float(policy["max_variance"]):
            continue
        best = (row, mean, sim, max_var)
        best_sim = sim
    if best is None:
        return None
    row, mean, sim, max_var = best
    dims = {k: round(float(mean.get(k, 0.0)), 4) for k in DIMENSIONS}
    support = int(row["count"] or 0)
    confidence = min(0.9, float(row["confidence"] or 0.0) * (0.65 + 0.35 * sim) * min(1.0, support / 5.0))
    return {
        "pattern_id": row["id"],
        "similarity": round(sim, 4),
        "variance": round(max_var, 6),
        "support": support,
        "dimensions": dims,
        "unresolved": round(float(mean.get("_unresolved", 0.0)), 4),
        "confidence": round(confidence, 4),
        "has_impact": float(row["impact_rate"] or 0.0) >= 0.5,
        "felt": "我记下了这件事，暂时没有太大波动。",
    }


def record_shadow(
    conn: sqlite3.Connection,
    memory_id: str,
    prediction: dict[str, Any],
    model_result: dict[str, Any],
) -> None:
    pred_dims = prediction.get("dimensions") or {}
    model_dims = model_result.get("dimensions") or {}
    err = sum(abs(float(pred_dims.get(k, 0.0)) - float(model_dims.get(k, 0.0))) for k in DIMENSIONS) / len(DIMENSIONS)
    agreement = 1 if err <= 0.15 else 0
    conn.execute(
        """INSERT INTO appraisal_shadow
           (memory_id, pattern_id, similarity, prediction_json, model_json, agreement, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (memory_id, prediction.get("pattern_id"), prediction.get("similarity"),
         json.dumps(prediction, ensure_ascii=False), json.dumps(model_result, ensure_ascii=False),
         agreement, db.utcnow()),
    )
    conn.execute(
        """UPDATE appraisal_policy SET
             shadow_checked=shadow_checked+1, shadow_match=shadow_match+?, updated_at=?
           WHERE id=1""",
        (agreement, db.utcnow()),
    )
    conn.commit()


def note_call(conn: sqlite3.Connection, *, pattern: bool) -> None:
    conn.execute(
        f"UPDATE appraisal_policy SET {('pattern_calls' if pattern else 'model_calls')}="
        f"{('pattern_calls' if pattern else 'model_calls')}+1, updated_at=? WHERE id=1",
        (db.utcnow(),),
    )
    conn.commit()


def set_mode(conn: sqlite3.Connection, mode: str) -> dict[str, Any]:
    if mode not in ("shadow", "auto", "off"):
        raise ValueError("mode must be shadow/auto/off")
    ensure_policy(conn)
    if mode == "auto":
        current = report(conn)
        checked = int(current.get("shadow_checked") or 0)
        accuracy = current.get("shadow_accuracy")
        if checked < 5 or accuracy is None or float(accuracy) < 0.7:
            raise ValueError(
                "auto 需要至少 5 次影子对照且准确率 >= 0.7；"
                f"当前 checked={checked}, accuracy={accuracy}"
            )
    conn.execute("UPDATE appraisal_policy SET mode=?, updated_at=? WHERE id=1", (mode, db.utcnow()))
    conn.commit()
    return report(conn)


def report(conn: sqlite3.Connection) -> dict[str, Any]:
    policy = ensure_policy(conn)
    patterns = conn.execute("SELECT * FROM appraisal_patterns ORDER BY count DESC").fetchall()
    checked = int(policy["shadow_checked"] or 0)
    matched = int(policy["shadow_match"] or 0)
    top = []
    for row in patterns[:8]:
        try:
            tokens = json.loads(row["tokens_json"] or "[]")
        except Exception:
            tokens = []
        top.append({
            "id": row["id"],
            "count": int(row["count"] or 0),
            "confidence": row["confidence"],
            "tokens": tokens,
        })
    return {
        "mode": policy["mode"],
        "patterns": len(patterns),
        "examples": sum(int(p["count"] or 0) for p in patterns),
        "model_calls": int(policy["model_calls"] or 0),
        "pattern_calls": int(policy["pattern_calls"] or 0),
        "coverage": round(
            (int(policy["pattern_calls"] or 0) / max(1, int(policy["pattern_calls"] or 0) + int(policy["model_calls"] or 0))), 4
        ),
        "shadow_checked": checked,
        "shadow_match": matched,
        "shadow_accuracy": round(matched / checked, 4) if checked else None,
        "top_patterns": top,
    }
