"""Export SoulCore enrichment as a SurfCore-compatible sidecar.

SurfCore's `memory-card-full.jsonl` stays canonical (raw text).
This module writes `memory-card-full.soulcore.jsonl` next to it:

  {"schema":"soulcore.enrichment.v1","record_id":"mem_xxx","soulcore":{...}}
  {"schema":"soulcore.extension.v1","record":{...SurfCore-shaped...},"soulcore":{...}}

SurfCore's read layer merges enrichment by record_id and appends extension records.
No SurfCore record is modified or deleted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from . import affect, correction, db, daybook, inbox, people, personality

SIDECAR_NAME = "memory-card-full.soulcore.jsonl"


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip().lower()


def _text_hash(text: str) -> str:
    return hashlib.sha1(_norm_text(text).encode("utf-8", "replace")).hexdigest()


def defense_clean(value: Any) -> Any:
    """Keep sidecar JSON finite/simple; never pass sqlite Row objects through."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): defense_clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [defense_clean(v) for v in value]
    return str(value)


def _latest_appraisal(conn: sqlite3.Connection, memory_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT dimensions_json, unresolved, confidence, has_impact, felt, thought,
                  baseline_json, delta_json, adjusted_json, created_at
           FROM appraisals WHERE memory_id=? ORDER BY id DESC LIMIT 1""",
        (memory_id,),
    ).fetchone()
    if not row:
        return None
    try:
        dims = json.loads(row["dimensions_json"])
    except Exception:
        dims = {}
    def _obj(name: str) -> dict[str, Any] | None:
        try:
            value = json.loads(row[name] or "null")
            return value if isinstance(value, dict) else None
        except Exception:
            return None
    baseline = _obj("baseline_json")
    delta = _obj("delta_json")
    adjusted = _obj("adjusted_json")
    felt = str(row["felt"] or "").strip()
    if not felt:
        valence = float(dims.get("valence", 0.0) or 0.0)
        unresolved = float(row["unresolved"] or 0.0)
        if unresolved >= 0.6:
            felt = "我还没完全弄明白，心里有点悬着。"
        elif valence <= -0.3:
            felt = "这件事让我不太舒服，我还在消化。"
        elif valence >= 0.3:
            felt = "这件事让我有点被托住，情绪往上走了一点。"
        else:
            felt = "我记下了这件事，暂时没有太大波动。"
    return {
        "dimensions": dims,
        "unresolved": row["unresolved"],
        "confidence": row["confidence"],
        "has_impact": bool(row["has_impact"]),
        "felt": felt[:160],
        "thought": str(row["thought"] or "").strip()[:300],
        "baseline": baseline,
        "delta": delta,
        "adjusted": adjusted,
        "appraised_at": row["created_at"],
    }


def _soulcore_payload(conn: sqlite3.Connection, m: sqlite3.Row) -> dict[str, Any]:
    appraisal = _latest_appraisal(conn, m["id"])
    delta = (appraisal or {}).get("delta")
    baseline = (appraisal or {}).get("baseline")
    dims = (appraisal or {}).get("dimensions")
    if delta is None and isinstance(baseline, dict) and isinstance(dims, dict):
        delta = {k: round(float(dims.get(k, 0.0)) - float(baseline.get(k, 0.0)), 4)
                 for k in dims}
    appraisal_view = {
        key: value for key, value in (appraisal or {}).items()
        if key not in ("baseline", "adjusted")
    }
    if delta is not None:
        appraisal_view["delta"] = delta
    correction_of = None
    if m["source"] == "surface-correction" and m["raw_json"]:
        try:
            correction_of = json.loads(m["raw_json"]).get("correction_of")
        except Exception:
            correction_of = None
    return {
        "schema": "soulcore.enrichment.v1",
        "source_id": m["id"],
        "person_id": m["person_id"],
        "speaker": m["speaker"],
        "identity_status": m["identity_status"] or "unknown",
        "felt": (appraisal or {}).get("felt", ""),
        "thought": (appraisal or {}).get("thought", ""),
        # 单条记忆只记录相对当日基准的偏离量；基准本身在 soulcore:affect:latest。
        "delta": delta,
        "superseded_by": correction.superseded_by(conn, m["id"]),
        "correction_of": correction_of,
        "appraisal": appraisal_view,
        "affect_weight": m["affect_weight"],
        "consolidation_state": m["consolidation_state"],
        "last_triggered_at": m["last_triggered_at"],
        "trigger_count": m["trigger_count"],
        "index": {
            "encoding_familiarity": m["encoding_familiarity"],
            "current_familiarity": m["current_familiarity"],
            "processing_fluency": m["processing_fluency"],
        },
    }


def _core_from_local(m: sqlite3.Row, *, extension: bool, owner_ids: set[str] | None = None) -> dict[str, Any]:
    text = str(m["text"] or "")
    speaker = m["speaker"] or ("我" if (m["identity_status"] or "") == "self" else "群友")
    rid = str(m["id"])
    if extension:
        rid = "soulcore:" + rid
    tags = ["qq", "soulcore"]
    if (m["identity_status"] or "") == "self":
        tags.append("self")
    if owner_ids and m["person_id"] and str(m["person_id"]) in owner_ids:
        tags.append("owner")
    if m["source"] == "surface-correction":
        tags.extend(["correction", "surface-scored"])
    return {
        "id": rid,
        "source": "soulcore",
        "sourceId": m["id"],
        "platform": "qq",
        "scope": "qq",
        "kind": "soulcore.correction" if m["source"] == "surface-correction" else "event",
        "title": f"{speaker}：{text[:60]}",
        "text": text[:4000],
        "speaker": speaker,
        "importance": int(round(float(m["importance"] or 0) * 100)),
        "tags": tags,
        "isSelf": (m["identity_status"] or "") == "self",
        "archivedAt": db.utcnow(),
    }


def _load_surfcore_records(memory_dir: Path) -> list[dict[str, Any]]:
    path = memory_dir / "memory-card-full.jsonl"
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("id"):
                out.append(rec)
    return out


def _profile(conn: sqlite3.Connection, person_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM person_profiles WHERE person_id=? ORDER BY version DESC LIMIT 1",
        (person_id,),
    ).fetchone()
    if not row:
        return {}
    try:
        hobbies = json.loads(row["hobbies_json"] or "[]")
    except Exception:
        hobbies = []
    return {
        "version": row["version"],
        "personality": row["personality"],
        "speaking_style": row["speaking_style"],
        "hobbies": hobbies,
        "summary": row["summary"],
        "confidence": row["confidence"],
        "source": row["source"],
        "status": row["status"],
    }


def _global_extensions(conn: sqlite3.Connection, now: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    # Person cards: one stable extension record per QQ identity.
    rows = conn.execute(
        """SELECT id, display_name, is_owner, message_count, familiarity, trust,
                  valence, unresolved, stance, action_hint, profile_status, profile_version
           FROM people ORDER BY message_count DESC"""
    ).fetchall()
    for p in rows:
        profile = _profile(conn, p["id"])
        payload = {
            "schema": "soulcore.enrichment.v1",
            "kind": "person",
            "identity_status": "resolved",
            "person_id": p["id"],
            "display_name": p["display_name"],
            "is_owner": bool(p["is_owner"]),
            "message_count": p["message_count"],
            "familiarity": p["familiarity"],
            "trust": p["trust"],
            "valence": p["valence"],
            "unresolved": p["unresolved"],
            "stance": p["stance"],
            "action_hint": p["action_hint"],
            "profile_status": p["profile_status"],
            "profile": profile,
        }
        text = (
            f"人物卡 {p['display_name']}（{p['id']}）：熟悉度 {p['familiarity']:.2f}，"
            f"信任 {p['trust']:.2f}，效价 {p['valence']:+.2f}，姿态 {p['stance']}。"
            f"{p['action_hint'] or ''}"
        )
        out.append({
            "schema": "soulcore.extension.v1",
            "record": {
                "id": f"soulcore:person:{p['id']}",
                "source": "soulcore",
                "platform": "qq",
                "scope": "qq",
                "kind": "soulcore.person",
                "title": f"人物卡：{p['display_name']}",
                "text": text,
                "speaker": "SoulCore",
                "importance": 40,
                "tags": ["soulcore", "person", "owner" if p["is_owner"] else "friend"],
                "isSelf": False,
                "archivedAt": now,
            },
            "soulcore": payload,
        })

    # Affect + P snapshot: one latest record; queryable by "情感/当前状态".
    latest = affect.compute_affect(conn, window=50)
    p = personality.compute_p(conn)
    out.append({
        "schema": "soulcore.extension.v1",
        "record": {
            "id": "soulcore:affect:latest",
            "source": "soulcore",
            "platform": "qq",
            "scope": "qq",
            "kind": "soulcore.affect",
            "title": "SoulCore 当前情感与人格基线",
            "text": (
                "当前情感：" + "；".join(f"{k} {v:.2f}" for k, v in latest.items()
                                       if isinstance(v, (int, float))) + "。"
                "当前人格基线 P：" + "；".join(f"{k} {v:.2f}" for k, v in p["p"].items()) + "。"
            ),
            "speaker": "SoulCore",
            "importance": 50,
            "tags": ["soulcore", "affect", "p"],
            "isSelf": False,
            "archivedAt": now,
        },
        "soulcore": {
            "schema": "soulcore.enrichment.v1",
            "kind": "affect",
            "identity_status": "system",
            "affect": latest,
            "p": p["p"],
            "p_memory_count": p["memory_count"],
            "prior_strength": p["prior_strength"],
        },
    })
    daily = daybook.latest(conn)
    if daily and isinstance(daily.get("baseline"), dict) and isinstance(daily.get("delta"), dict):
        base = daily["baseline"]
        delta = daily["delta"]
        end = daily.get("end") or {}
        out.append({
            "schema": "soulcore.extension.v1",
            "record": {
                "id": f"soulcore:daily:{daily['day_key']}",
                "source": "soulcore",
                "platform": "qq",
                "scope": "qq",
                "kind": "soulcore.daily",
                "title": f"SoulCore 每日基准与累计偏移 {daily['day_key']}",
                "text": (
                    "日初基准：" + "；".join(f"{k} {v:.2f}" for k, v in base.items())
                    + "。当日累计偏移：" + "；".join(f"{k} {v:+.2f}" for k, v in delta.items())
                    + "。清洗后：" + "；".join(f"{k} {v:.2f}" for k, v in end.items())
                    + f"。kept {daily.get('kept', 0)} / ignored {daily.get('ignored', 0)}。"
                ),
                "speaker": "SoulCore",
                "importance": 55,
                "tags": ["soulcore", "daily", "baseline", "delta"],
                "isSelf": False,
                "archivedAt": now,
            },
            "soulcore": {
                "schema": "soulcore.enrichment.v1",
                "kind": "daily_summary",
                "identity_status": "system",
                "day_key": daily["day_key"],
                "baseline": base,
                "delta": delta,
                "end": end,
                "kept": daily.get("kept", 0),
                "ignored": daily.get("ignored", 0),
                "baseline_at": daily.get("baseline_at"),
                "end_at": daily.get("end_at"),
            },
        })
    return out


def export_surfcore(
    conn: sqlite3.Connection,
    *,
    surfcore_root: str | Path | None = None,
    include_global: bool = True,
) -> dict[str, Any]:
    char_dir = inbox._char_dir(surfcore_root)
    memory_dir = char_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    full = _load_surfcore_records(memory_dir)
    by_id = {str(r.get("id")): r for r in full if r.get("id")}
    by_text: dict[str, dict[str, Any]] = {}
    for r in full:
        by_text.setdefault(_text_hash(r.get("text", "")), r)

    now = db.utcnow()
    lines: list[dict[str, Any]] = []
    enrichment = 0
    extension = 0
    matched_ids: set[str] = set()

    rows = conn.execute(
        """SELECT * FROM memories
           WHERE source IN ('surfcore', 'surfcore-inbox', 'surface-correction')
           ORDER BY COALESCE(ts, created_at) ASC"""
    ).fetchall()
    owner_ids = {
        str(r["id"]) for r in conn.execute("SELECT id FROM people WHERE is_owner=1").fetchall()
    }
    for m in rows:
        local_id = str(m["id"])
        target = None
        if local_id.startswith("surfcore:"):
            target = by_id.get(local_id.split(":", 1)[1])
        if target is None:
            target = by_text.get(_text_hash(m["text"]))
        payload = _soulcore_payload(conn, m)
        if target is not None:
            rid = str(target.get("id"))
            if rid in matched_ids:
                continue
            matched_ids.add(rid)
            lines.append({
                "schema": "soulcore.enrichment.v1",
                "record_id": rid,
                "soulcore": payload,
            })
            enrichment += 1
        else:
            lines.append({
                "schema": "soulcore.extension.v1",
                "record": _core_from_local(m, extension=True, owner_ids=owner_ids),
                "soulcore": payload,
            })
            extension += 1

    if include_global:
        globals_ = _global_extensions(conn, now)
        lines.extend(globals_)
        extension += len(globals_)

    sidecar = memory_dir / SIDECAR_NAME
    tmp = memory_dir / (SIDECAR_NAME + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for item in lines:
            fh.write(json.dumps(defense_clean(item), ensure_ascii=False) + "\n")
    os.replace(tmp, sidecar)
    return {
        "sidecar": str(sidecar),
        "enrichment": enrichment,
        "extension": extension,
        "surfcore_records": len(full),
        "local_real_records": len(rows),
        "lines": len(lines),
    }
