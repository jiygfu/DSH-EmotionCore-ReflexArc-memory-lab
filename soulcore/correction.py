"""Correction loop for failed/uncertain appraisals.

A failed AI appraisal becomes a question. The surface layer can resolve it with
its own score even when the owner has not answered. Resolution creates a
surface-scored correction memory and marks the question resolved.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from . import appraisal_learning, db, personality

DIMENSIONS = (
    "security", "trust", "self_efficacy", "caution",
    "sociability", "openness", "valence", "arousal",
)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def enqueue(
    conn: sqlite3.Connection,
    *,
    memory_id: str,
    package: dict[str, Any],
) -> str:
    qid = "q_" + hashlib.sha1(
        (memory_id + "|" + str(package.get("error") or "") + "|" + db.utcnow()).encode("utf-8")
    ).hexdigest()[:16]
    conn.execute(
        """INSERT INTO appraisal_questions
           (id, memory_id, package_json, status, created_at)
           VALUES (?, ?, ?, 'pending', ?)""",
        (qid, memory_id, json.dumps(package, ensure_ascii=False), db.utcnow()),
    )
    conn.commit()
    return qid


def pending(conn: sqlite3.Connection, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT * FROM appraisal_questions
           WHERE status='pending' ORDER BY created_at ASC LIMIT ?""",
        (max(1, int(limit)),),
    ).fetchall()
    out = []
    for row in rows:
        try:
            pkg = json.loads(row["package_json"])
        except Exception:
            pkg = {}
        out.append({"id": row["id"], "memory_id": row["memory_id"],
                    "package": pkg, "created_at": row["created_at"]})
    return out


def _derive_felt(dims: dict[str, float], unresolved: float) -> str:
    valence = float(dims.get("valence", 0.0))
    if unresolved >= 0.6:
        return "我还没完全弄明白，心里有点悬着。"
    if valence <= -0.3:
        return "这件事让我不太舒服，我还在消化。"
    if valence >= 0.3:
        return "这件事让我有点被托住，情绪往上走了一点。"
    return "我记下了这件事，暂时没有太大波动。"


def resolve(
    conn: sqlite3.Connection,
    *,
    question_id: str,
    answer: str = "",
    score: dict[str, Any] | None = None,
    summary: str = "",
    felt: str = "",
) -> dict[str, Any]:
    q = conn.execute(
        "SELECT * FROM appraisal_questions WHERE id=?", (question_id,)
    ).fetchone()
    if not q:
        raise ValueError("question not found")
    if q["status"] != "pending":
        raise ValueError("question already resolved")
    try:
        pkg = json.loads(q["package_json"])
    except Exception:
        pkg = {}
    old = conn.execute("SELECT * FROM memories WHERE id=?", (q["memory_id"],)).fetchone()
    if not old:
        raise ValueError("original memory not found")
    # Surface may score directly; if it omitted a dimension, use the code score.
    fallback = (pkg.get("code") or {}).get("dimensions") or {}
    src = score if isinstance(score, dict) else fallback
    dims = {k: round(_clamp(float(src.get(k, fallback.get(k, 0.5))), -1 if k == "valence" else 0,
                            1), 4) for k in DIMENSIONS}
    unresolved = round(_clamp(float((score or {}).get("unresolved", pkg.get("unresolved", 0.35)))), 4)
    confidence = round(_clamp(float((score or {}).get("confidence", 0.8))), 4)
    has_impact = bool((score or {}).get("has_impact", True))
    baseline = personality.compute_p(conn).get("p") or {}
    delta = {k: round(dims[k] - float(baseline.get(k, 0.0)), 4) for k in DIMENSIONS}
    adjusted = {k: round(_clamp(float(baseline.get(k, 0.0)) + delta[k],
                                -1 if k == "valence" else 0, 1), 4) for k in DIMENSIONS}
    old_text = str(old["text"] or "")
    body = [
        f"【记忆修正｜原记录 {old['id']}】",
        f"原记录：{old_text[:600]}",
    ]
    if answer:
        body.append(f"owner 解答：{str(answer)[:600]}")
    if summary:
        body.append(f"表层结论：{str(summary)[:600]}")
    body.append(
        "表层评分：" + "；".join(f"{k} {dims[k]:.2f}" for k in DIMENSIONS)
        + f"；unresolved {unresolved:.2f}"
    )
    text = "\n".join(body)[:4000]
    new_id = f"surface-correction:{question_id}"
    db.upsert_memory(
        conn,
        source="surface-correction",
        source_record_id=question_id,
        text=text,
        ts=db.utcnow(),
        scope=str(old["scope"] or "pet"),
        importance=max(0.5, float(old["importance"] or 0.0)),
        speaker="SoulCore",
        speaker_id=old["speaker_id"],
        person_id=old["person_id"],
        identity_status=old["identity_status"] or "resolved",
        group_id=old["group_id"],
        conversation_key=old["conversation_key"],
        raw={
            "correction_of": old["id"],
            "question_id": question_id,
            "answer": answer,
            "summary": summary,
            "surface": True,
        },
    )
    # Minimal version/status chain; the old raw record stays queryable.
    now = db.utcnow()
    new_version = int(old["version"] or 1) + 1
    conn.execute(
        """UPDATE memories
           SET source_kind='correction', status='active', version=?,
               valid_from=?, last_confirmed_at=?, updated_at=?
           WHERE id=?""",
        (new_version, now, now, now, new_id),
    )
    conn.execute(
        """UPDATE memories
           SET status='superseded', valid_to=?, consolidation_state='superseded', updated_at=?
           WHERE id=?""",
        (now, now, old["id"]),
    )
    db.save_appraisal(
        conn, new_id,
        dimensions=dims,
        unresolved=unresolved,
        confidence=confidence,
        evidence=(summary or answer or "surface correction")[:240],
        has_impact=has_impact,
        latency_ms=0,
        raw_response="",
        appraiser_id="surface-v1",
        felt=(felt or _derive_felt(dims, unresolved))[:160],
        thought=(summary or answer or "surface correction")[:300],
        baseline=baseline,
        delta=delta,
        adjusted=adjusted,
        feature=appraisal_learning.extract(text),
    )
    # 旧记录不再参与 P；全量档案仍可检索。
    conn.execute(
        "UPDATE memories SET affect_weight=0, consolidation_state='superseded', updated_at=? WHERE id=?",
        (db.utcnow(), old["id"]),
    )
    conn.execute(
        """UPDATE appraisal_questions
           SET status='resolved', answer=?, surface_json=?, correction_id=?, resolved_at=?
           WHERE id=?""",
        (answer[:2000], json.dumps({"score": dims, "summary": summary, "felt": felt},
                                   ensure_ascii=False),
         new_id, db.utcnow(), question_id),
    )
    conn.commit()
    return {
        "ok": True,
        "question_id": question_id,
        "old_memory_id": old["id"],
        "new_memory_id": new_id,
        "score": dims,
        "unresolved": unresolved,
        "confidence": confidence,
        "felt": felt or _derive_felt(dims, unresolved),
    }


def superseded_by(conn: sqlite3.Connection, memory_id: str) -> str | None:
    row = conn.execute(
        """SELECT correction_id FROM appraisal_questions
           WHERE memory_id=? AND status='resolved' AND correction_id IS NOT NULL
           ORDER BY resolved_at DESC LIMIT 1""",
        (memory_id,),
    ).fetchone()
    return row["correction_id"] if row else None
