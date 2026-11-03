"""Per-person identity, daily relationship state, and conversation context.

SurfCore's memory card keeps only a display `speaker` and drops `senderId`.
This module keeps the stable identity locally:

    person_id = qq:<user_id>

Relationship values are derived from appraisals of that person's memories,
refreshed daily. They are not hardcoded "friend/enemy" labels.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from typing import Any

from . import appraise, db

PROFILE_THRESHOLD = 10
PROFILE_REFRESH_MESSAGES = 10

STANCE_ACTIONS = {
    "build": "#行动：主动接住对方的话，记住他提过的小事，适度延展；不刻意讨好。",
    "casual": "#行动：自然回应，保持礼貌；不主动深挖对方私事，也不冷淡。",
    "cautious": "#行动：简短回应，先观察；不主动透露自己的私事，不轻易承诺。",
}


def derive_stance(
    *,
    trust: float,
    valence: float,
    familiarity: float,
    unresolved: float,
) -> tuple[str, str]:
    if trust <= 0.45 or valence <= -0.15 or unresolved >= 0.55:
        stance = "cautious"
    elif trust >= 0.55 and valence >= 0.12 and familiarity >= 0.50 and unresolved < 0.55:
        stance = "build"
    else:
        stance = "casual"
    return stance, STANCE_ACTIONS[stance]


PROFILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "personality": {"type": "string", "minLength": 1, "maxLength": 240},
        "speaking_style": {"type": "string", "minLength": 1, "maxLength": 240},
        "hobbies": {
            "type": "array", "maxItems": 5,
            "items": {"type": "string", "minLength": 1, "maxLength": 40},
        },
        "summary": {"type": "string", "minLength": 1, "maxLength": 400},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["personality", "speaking_style", "hobbies", "summary", "confidence"],
}

PROFILE_PROMPT = """你是群聊人物侧写器，不是聊天角色。请只输出 JSON，不要诊断，不要用临床词。

只根据这些发言，给这个人一个“暂定侧写”：
- personality：性格倾向，限定 2~4 个短句；
- speaking_style：说话风格/语气/常用表达；
- hobbies：能从发言里看到的兴趣，最多 5 个；没有就给空数组；
- summary：一段简短总结；
- confidence：0~1，样本少就给低置信度。

不要断言，不要编造没出现过的信息。材料：
{context}
"""


def person_id_for(user_id: str, platform: str = "qq") -> str:
    return f"{platform}:{str(user_id).strip()}"


def upsert_person(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    display_name: str,
    platform: str = "qq",
    is_owner: bool = False,
    seen_at: str | None = None,
    increment: bool = False,
) -> str:
    pid = person_id_for(user_id, platform)
    now = db.localnow()
    at = seen_at or now
    row = conn.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone()
    if row:
        aliases = []
        try:
            aliases = json.loads(row["aliases_json"] or "[]")
        except Exception:
            aliases = []
        if display_name and display_name not in aliases:
            aliases.append(display_name)
        conn.execute(
            """UPDATE people
               SET display_name=?, aliases_json=?, is_owner=MAX(is_owner, ?),
                   last_seen=?, message_count=message_count + ?, updated_at=?
               WHERE id=?""",
            (display_name or row["display_name"], json.dumps(aliases[-20:], ensure_ascii=False),
             1 if is_owner else 0, at, 1 if increment else 0, now, pid),
        )
        conn.commit()
        return pid
    conn.execute(
        """INSERT INTO people
           (id, platform, user_id, display_name, aliases_json, is_owner,
            first_seen, last_seen, message_count, familiarity, trust, valence,
            unresolved, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0.5, 0.0, 0.0, ?, ?)""",
        (pid, platform, str(user_id), display_name, json.dumps([display_name] if display_name else [], ensure_ascii=False),
         1 if is_owner else 0, at, at, 1 if increment else 0, now, now),
    )
    conn.commit()
    return pid


def refresh(conn: sqlite3.Connection, *, day: str | None = None, ema: float = 0.7) -> dict[str, int]:
    """Aggregate today's person-linked appraisals into a daily relationship state."""
    d = day or datetime.now().astimezone().date().isoformat()
    people = conn.execute(
        """SELECT DISTINCT p.* FROM people p
           JOIN memories m ON m.person_id = p.id
           WHERE substr(COALESCE(m.ts, m.created_at), 1, 10) = ?
              OR substr(COALESCE(m.last_triggered_at, ''), 1, 10) = ?""",
        (d, d),
    ).fetchall()
    updated = 0
    for person in people:
        rows = conn.execute(
            """SELECT m.id, a.dimensions_json, a.unresolved, a.confidence
               FROM memories m
               JOIN appraisals a ON a.id = (
                   SELECT id FROM appraisals WHERE memory_id = m.id ORDER BY id DESC LIMIT 1
               )
               WHERE m.person_id=?
                 AND (substr(COALESCE(m.ts, m.created_at), 1, 10) = ?
                      OR substr(COALESCE(m.last_triggered_at, ''), 1, 10) = ?)""",
            (person["id"], d, d),
        ).fetchall()
        count = len(rows)
        if not count:
            continue
        trust = valence = unresolved = 0.0
        weight_sum = 0.0
        evidence = []
        for r in rows:
            try:
                dims = json.loads(r["dimensions_json"])
            except Exception:
                continue
            w = max(0.05, float(r["confidence"] or 0.0))
            trust += float(dims.get("trust", 0.5)) * w
            valence += float(dims.get("valence", 0.0)) * w
            unresolved += float(r["unresolved"] or 0.0) * w
            weight_sum += w
            evidence.append(r["id"])
        if not weight_sum:
            continue
        trust = round(trust / weight_sum, 4)
        valence = round(valence / weight_sum, 4)
        unresolved = round(unresolved / weight_sum, 4)
        prev = conn.execute(
            "SELECT * FROM person_daily WHERE person_id=? AND day_key < ? ORDER BY day_key DESC LIMIT 1",
            (person["id"], d),
        ).fetchone()
        if prev:
            t = round(ema * float(prev["trust"]) + (1 - ema) * trust, 4)
            v = round(ema * float(prev["valence"]) + (1 - ema) * valence, 4)
            u = round(ema * float(prev["unresolved"]) + (1 - ema) * unresolved, 4)
        else:
            t, v, u = trust, valence, unresolved
        total = int(person["message_count"] or 0)
        familiarity = round(1.0 - math.exp(-max(0, total) / 8.0), 4)
        stance, action = derive_stance(
            trust=t, valence=v, familiarity=familiarity, unresolved=u
        )
        profile_status = person["profile_status"] or "none"
        basis = int(person["profile_basis_count"] or 0)
        if total >= PROFILE_THRESHOLD:
            if profile_status in ("none", "due"):
                profile_status = "due"
            elif profile_status == "draft" and total - basis >= PROFILE_REFRESH_MESSAGES:
                profile_status = "due"
        summary = (
            f"今天有 {count} 条相关互动；"
            f"信任 {t:.2f}，效价 {v:+.2f}，未解决 {u:.2f}，"
            f"累计熟悉度 {familiarity:.2f}；关系姿态 {stance}。"
        )
        now = db.utcnow()
        conn.execute(
            """INSERT INTO person_daily
               (person_id, day_key, message_count, familiarity, trust, valence,
                unresolved, stance, action_hint, summary, evidence_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(person_id, day_key) DO UPDATE SET
                 message_count=excluded.message_count,
                 familiarity=excluded.familiarity,
                 trust=excluded.trust,
                 valence=excluded.valence,
                 unresolved=excluded.unresolved,
                 stance=excluded.stance,
                 action_hint=excluded.action_hint,
                 summary=excluded.summary,
                 evidence_json=excluded.evidence_json,
                 updated_at=excluded.updated_at""",
            (person["id"], d, count, familiarity, t, v, u, stance, action, summary,
             json.dumps(evidence, ensure_ascii=False), now, now),
        )
        conn.execute(
            """UPDATE people
               SET familiarity=?, trust=?, valence=?, unresolved=?,
                   stance=?, action_hint=?, profile_status=?,
                   last_refreshed_at=?, updated_at=?
               WHERE id=?""",
            (familiarity, t, v, u, stance, action, profile_status, now, now, person["id"]),
        )
        updated += 1
    conn.commit()
    return {"day": d, "people": len(people), "updated": updated}


def context(conn: sqlite3.Connection, person_id: str, *, day: str | None = None) -> dict[str, Any] | None:
    d = day or datetime.now().astimezone().date().isoformat()
    person = conn.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if not person:
        return None
    daily = conn.execute(
        "SELECT * FROM person_daily WHERE person_id=? AND day_key=?", (person_id, d)
    ).fetchone()
    profile = conn.execute(
        "SELECT * FROM person_profiles WHERE person_id=? ORDER BY version DESC LIMIT 1",
        (person_id,),
    ).fetchone()
    profile_out = None
    if profile:
        profile_out = {
            "version": profile["version"],
            "personality": profile["personality"],
            "speaking_style": profile["speaking_style"],
            "hobbies": json.loads(profile["hobbies_json"] or "[]"),
            "summary": profile["summary"],
            "confidence": float(profile["confidence"] or 0.0),
            "source": profile["source"],
            "status": profile["status"],
        }
    return {
        "id": person["id"],
        "display_name": person["display_name"],
        "aliases": json.loads(person["aliases_json"] or "[]"),
        "is_owner": bool(person["is_owner"]),
        "message_count": int(person["message_count"] or 0),
        "familiarity": float(person["familiarity"] or 0.0),
        "trust": float(person["trust"] or 0.5),
        "valence": float(person["valence"] or 0.0),
        "unresolved": float(person["unresolved"] or 0.0),
        "tags": json.loads(person["tags_json"] or "[]") if "tags_json" in person.keys() else [],
        "stance": person["stance"] or "casual",
        "action_hint": person["action_hint"] or STANCE_ACTIONS["casual"],
        "profile_status": person["profile_status"] or "none",
        "profile": profile_out,
        "today": dict(daily) if daily else None,
    }


def tag_person(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    display_name: str = "",
    tags: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Add stable labels to a person's impression without touching P/values."""
    pid = upsert_person(conn, user_id=str(user_id), display_name=str(display_name or user_id))
    row = conn.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone()
    if not row:
        raise ValueError("person not found")
    try:
        old = json.loads(row["tags_json"] or "[]")
    except Exception:
        old = []
    merged: list[str] = []
    for item in list(old) + list(tags or []):
        text = str(item or "").strip()[:40]
        if text and text not in merged:
            merged.append(text)
    now = db.localnow()
    conn.execute(
        "UPDATE people SET tags_json=?, updated_at=? WHERE id=?",
        (json.dumps(merged[-20:], ensure_ascii=False), now, pid),
    )
    conn.commit()
    return context(conn, pid) or {"id": pid, "tags": merged}


def profile_due(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, display_name, message_count, profile_status
           FROM people
           WHERE message_count >= ?
             AND COALESCE(profile_status, 'none') IN ('none', 'due')
           ORDER BY message_count DESC LIMIT ?""",
        (PROFILE_THRESHOLD, max(1, int(limit))),
    ).fetchall()
    return [dict(r) for r in rows]


def generate_profile(
    conn: sqlite3.Connection,
    person_id: str,
    *,
    model: str = db.MODEL,
    timeout: int = 180,
) -> dict[str, Any]:
    person = conn.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if not person:
        raise ValueError(f"person not found: {person_id}")
    if int(person["message_count"] or 0) < PROFILE_THRESHOLD:
        raise ValueError(f"need >= {PROFILE_THRESHOLD} messages")
    rows = conn.execute(
        """SELECT id, text FROM memories WHERE person_id=?
           ORDER BY COALESCE(ts, created_at) DESC LIMIT 20""",
        (person_id,),
    ).fetchall()
    context = {
        "display_name": person["display_name"],
        "message_count": int(person["message_count"] or 0),
        "messages": [{"id": r["id"], "text": (r["text"] or "")[:600]} for r in rows],
    }
    body = {
        "model": model,
        "prompt": PROFILE_PROMPT.format(context=json.dumps(context, ensure_ascii=False)[:6000]),
        "stream": False,
        "format": PROFILE_SCHEMA,
        "keep_alive": "30s",
        "options": {
            "temperature": 0.3,
            "top_p": 0.9,
            "num_ctx": 3072,
            "num_predict": 360,
            "num_thread": 4,
        },
    }
    data = appraise._post_json("/api/generate", body, timeout=timeout)
    obj = json.loads(appraise._strip_json(str(data.get("response") or "")))
    personality = str(obj.get("personality") or "").strip()[:240]
    style = str(obj.get("speaking_style") or "").strip()[:240]
    hobbies = [str(x).strip()[:40] for x in (obj.get("hobbies") or []) if str(x).strip()][:5]
    summary = str(obj.get("summary") or "").strip()[:400]
    confidence = max(0.0, min(1.0, float(obj.get("confidence") or 0.0)))
    if not personality or not style or not summary:
        raise ValueError("profile missing required fields")
    version = int(conn.execute(
        "SELECT COALESCE(MAX(version),0) FROM person_profiles WHERE person_id=?",
        (person_id,),
    ).fetchone()[0]) + 1
    now = db.utcnow()
    conn.execute(
        """INSERT INTO person_profiles
           (person_id, version, personality, speaking_style, hobbies_json, summary,
            evidence_json, confidence, source, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'local-2b', 'draft', ?)""",
        (person_id, version, personality, style, json.dumps(hobbies, ensure_ascii=False),
         summary, json.dumps([r["id"] for r in rows], ensure_ascii=False), confidence, now),
    )
    conn.execute(
        """UPDATE people SET profile_status='draft', profile_version=?,
           profile_basis_count=?, updated_at=?
           WHERE id=?""",
        (version, int(person["message_count"] or 0), now, person_id),
    )
    conn.commit()
    return {
        "person_id": person_id,
        "version": version,
        "personality": personality,
        "speaking_style": style,
        "hobbies": hobbies,
        "summary": summary,
        "confidence": confidence,
        "status": "draft",
    }


def today_people(conn: sqlite3.Connection, *, day: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
    d = day or datetime.now().astimezone().date().isoformat()
    rows = conn.execute(
        """SELECT DISTINCT p.id FROM people p
           JOIN memories m ON m.person_id = p.id
           WHERE substr(COALESCE(m.ts, m.created_at), 1, 10) = ?
              OR substr(COALESCE(m.last_triggered_at, ''), 1, 10) = ?
           LIMIT ?""",
        (d, d, max(1, int(limit))),
    ).fetchall()
    out = []
    for r in rows:
        c = context(conn, r["id"], day=d)
        if c:
            out.append(c)
    return out


def record_feedback(
    conn: sqlite3.Connection,
    person_id: str,
    *,
    kind: str,
    valence: float | None = None,
    trust: float | None = None,
    note: str = "",
    memory_id: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO person_feedback
           (person_id, memory_id, kind, valence, trust, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (person_id, memory_id, kind, valence, trust, note[:300], db.utcnow()),
    )
    conn.commit()
