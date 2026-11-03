"""Deterministic episode summaries.

The raw memories remain untouched. Episodes are an index layer:
- group by day + conversation + time gap;
- summary/key quote from existing text and appraisals;
- no model call in this first pass.

A later local-model pass can improve wording, but this fallback always exists.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DIMENSIONS = ("security", "trust", "self_efficacy", "caution", "sociability", "openness", "valence", "arousal")
GAP_MINUTES = 20
MAX_ITEMS = 12
REFLECTION_MARKERS = (
    "常驻提示词",
    "唤醒卡",
    "交接单",
    "提示词有哪些",
    "提示词里",
)


def _parse(ts: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.astimezone()
        return d.astimezone()
    except Exception:
        return None


def _clip(text: str, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def build_day(conn: sqlite3.Connection, *, day: str | None = None) -> dict[str, Any]:
    key = day or datetime.now().astimezone().date().isoformat()
    rows = conn.execute(
        """SELECT m.id, m.text, m.ts, m.speaker, m.scope, m.conversation_key,
                  m.importance, m.source, m.identity_status,
                  a.dimensions_json, a.felt, a.delta_json, a.unresolved, a.confidence
           FROM memories m
           LEFT JOIN appraisals a ON a.id = (
             SELECT id FROM appraisals WHERE memory_id=m.id ORDER BY id DESC LIMIT 1
           )
           WHERE m.source IN ('surfcore','surfcore-inbox','surface-correction','emotioncore-adapter')
             AND m.appraisal_status='done'
             AND m.status='active'
             AND COALESCE(m.affect_weight, 1.0) > 0
             AND COALESCE(m.consolidation_state, 'none') <> 'ignored'
           ORDER BY m.ts ASC"""
    ).fetchall()
    groups: list[list[sqlite3.Row]] = []
    current: list[sqlite3.Row] = []
    last_dt: datetime | None = None
    for row in rows:
        dt = _parse(row["ts"])
        if dt is None or dt.date().isoformat() != key:
            continue
        if current and last_dt is not None:
            gap = dt - last_dt
            same_conv = (row["conversation_key"] or "") == (current[-1]["conversation_key"] or "")
            if gap > timedelta(minutes=GAP_MINUTES) or not same_conv or len(current) >= MAX_ITEMS:
                groups.append(current)
                current = []
        current.append(row)
        last_dt = dt
    if current:
        groups.append(current)

    old_status = {}
    try:
        for row in conn.execute("SELECT id,status,closed_at,resolution_note,closure_confidence,closure_source,reviewed_at,thread_id,continues_episode_id,last_seen_at FROM episodes WHERE day=?", (key,)):
            old_status[row["id"]] = (row["status"] or "open", row["closed_at"], row["resolution_note"], row["closure_confidence"], row["closure_source"], row["reviewed_at"], row["thread_id"], row["continues_episode_id"], row["last_seen_at"])
    except Exception:
        old_status = {}
    conn.execute("DELETE FROM episodes WHERE day=?", (key,))
    created = 0
    for items in groups:
        if not items:
            continue
        first, last = items[0], items[-1]
        start = _parse(first["ts"])
        end = _parse(last["ts"])
        if not start or not end:
            continue
        participants = sorted({str(x["speaker"] or "") for x in items if x["speaker"]})
        # 关键引语：重要性最高、其次情绪绝对值最大；稳定按 id 兜底。
        def score(x: sqlite3.Row) -> tuple[float, float, str]:
            dims: dict[str, Any] = {}
            try:
                dims = json.loads(x["dimensions_json"] or "{}")
            except Exception:
                pass
            affect = abs(float(dims.get("valence", 0.0) or 0.0)) + float(x["unresolved"] or 0.0)
            return (float(x["importance"] or 0.0), affect, str(x["id"]))
        quote_row = max(items, key=score)
        summary_bits = []
        for x in (items[:1] + ([quote_row] if quote_row["id"] != items[0]["id"] else [])):
            t = _clip(x["text"], 90)
            if t and t not in summary_bits:
                summary_bits.append(t)
        summary = "；".join(summary_bits)[:300]
        if len(items) > 2:
            summary += f"（共 {len(items)} 条）"
        dims: dict[str, Any] = {}
        try:
            dims = json.loads(quote_row["dimensions_json"] or "{}")
        except Exception:
            pass
        delta = {}
        try:
            delta = json.loads(quote_row["delta_json"] or "{}")
        except Exception:
            pass
        importance = max(float(x["importance"] or 0.0) for x in items)
        # memory.importance 同步值通常为 0；从 appraisal 的 affect/unresolved/confidence
        # 派生一个可排序的 episode 重要性，不改原始 memory。
        def episode_importance(x: sqlite3.Row) -> float:
            dims: dict[str, Any] = {}
            try:
                dims = json.loads(x["dimensions_json"] or "{}")
            except Exception:
                pass
            affect = abs(float(dims.get("valence", 0.0) or 0.0)) + 0.5 * abs(float(dims.get("arousal", 0.0) or 0.0))
            unresolved = float(x["unresolved"] or 0.0)
            confidence = float(x["confidence"] or 0.0)
            return 0.55 * affect + 0.25 * unresolved + 0.10 * confidence
        importance = max(importance, max(episode_importance(x) for x in items))
        unresolved = max(float(x["unresolved"] or 0.0) for x in items)
        source_kind = "correction" if any(x["source"] == "surface-correction" for x in items) else (
            "agent_dialogue" if any((x["identity_status"] or "") == "self" for x in items) else "dialog"
        )
        if any(marker in summary or marker in str(quote_row["text"] or "") for marker in REFLECTION_MARKERS):
            source_kind = "reflection"
        eid = "ep_" + hashlib.sha1(
            f"{key}|{first['conversation_key'] or ''}|{first['ts']}|{last['id']}".encode("utf-8")
        ).hexdigest()[:16]
        now = datetime.now().astimezone().isoformat()
        conn.execute(
            """INSERT INTO episodes
               (id, day, start_at, end_at, conversation_key, participants_json, trigger,
                summary, key_quote, felt, delta_json, unresolved, importance,
                raw_ids_json, topics_json, source_kind, created_at, updated_at,
                status, closed_at, resolution_note, closure_confidence, closure_source, reviewed_at, thread_id, continues_episode_id, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid, key, first["ts"], last["ts"], first["conversation_key"] or "",
                json.dumps(participants, ensure_ascii=False), "sleep",
                summary, _clip(quote_row["text"], 180), str(quote_row["felt"] or ""),
                json.dumps(delta, ensure_ascii=False), unresolved, importance,
                json.dumps([x["id"] for x in items], ensure_ascii=False),
                json.dumps([], ensure_ascii=False), source_kind, now, now,
                *old_status.get(eid, ("open", None, None, None, None, None, None, None, None)),
            ),
        )
        created += 1
    conn.commit()
    return {"ok": True, "day": key, "episodes": created, "memories": sum(len(g) for g in groups)}


def list_day(conn: sqlite3.Connection, *, day: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    key = day or datetime.now().astimezone().date().isoformat()
    rows = conn.execute(
        "SELECT * FROM episodes WHERE day=? ORDER BY start_at ASC LIMIT ?",
        (key, max(1, min(100, int(limit)))),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("participants_json", "delta_json", "raw_ids_json", "topics_json"):
            try:
                d[k[:-5]] = json.loads(d.pop(k) or "null")
            except Exception:
                d[k[:-5]] = None
                d.pop(k, None)
        out.append(d)
    return out


def render_cards(conn: sqlite3.Connection, *, day: str | None = None,
                 limit: int = 5, max_chars: int = 1500) -> str:
    key = day or datetime.now().astimezone().date().isoformat()
    rows = conn.execute(
        """SELECT * FROM episodes WHERE day=? AND importance > 0
           AND source_kind != 'reflection'
           ORDER BY importance DESC, start_at DESC LIMIT ?""",
        (key, max(1, min(80, int(limit) * 8))),
    ).fetchall()
    # Keep private/group both represented in the static L2 fallback instead of
    # letting one high-volume conversation occupy all five slots.
    selected = []
    seen_convs = set()
    for r in rows:
        conv = str(r["conversation_key"] or "")
        if conv and conv not in seen_convs:
            selected.append(r)
            seen_convs.add(conv)
    for r in rows:
        if len(selected) >= max(1, min(20, int(limit))):
            break
        if r not in selected:
            selected.append(r)
    rows = selected[:max(1, min(20, int(limit)))]
    if not rows:
        return ""
    lines = ["【事件索引（L2；原始记忆仍在本地，需要细节再查）】"]
    for r in rows:
        st = str(r["start_at"] or "")
        try:
            dt = datetime.fromisoformat(st.replace("Z", "+00:00")).astimezone()
            clock = dt.strftime("%H:%M") if dt.date().isoformat() == key else dt.strftime("%m-%d %H:%M")
        except Exception:
            clock = st[11:16] if len(st) >= 16 else st
        who = ""
        try:
            participants = json.loads(r["participants_json"] or "[]")
            if participants:
                who = "、".join(str(x) for x in participants[:3])
        except Exception:
            pass
        bits = []
        if who:
            bits.append(f"{who}：")
        bits.append(_clip(r["summary"], 130))
        if r["key_quote"]:
            bits.append(f"关键：「{_clip(r['key_quote'], 70)}」")
        if r["felt"]:
            bits.append(f"感受：{_clip(r['felt'], 50)}")
        lines.append(f"- {clock} " + " ".join(bits))
    text = "\n".join(lines)
    return text[:max(200, int(max_chars))]


def _state_dir() -> Path:
    try:
        cfg = json.loads((Path.home() / ".dsh" / "surfcore" / "config.json").read_text(encoding="utf-8"))
        root = Path(str(cfg.get("qqbotRoot") or "")).expanduser()
        if root:
            return root / "state"
    except Exception:
        pass
    return Path.home() / ".dsh" / "surfcore" / "state"


def write_index(conn: sqlite3.Connection, *, days: int = 7,
                out: str | None = None) -> str:
    """Write a compact local index for query-aware L2 selection."""
    target = Path(out) if out else (_state_dir() / "episode-index.json")
    rows = conn.execute(
        """SELECT id, day, start_at, end_at, participants_json, summary, key_quote,
                  felt, importance, unresolved, source_kind, raw_ids_json
           FROM episodes
           WHERE day >= date('now','localtime', ?) AND importance > 0
             AND source_kind != 'reflection'
           ORDER BY start_at DESC LIMIT 200""",
        (f"-{max(1, int(days)) - 1} days",),
    ).fetchall()
    out_rows = []
    for r in rows:
        d = dict(r)
        for key in ("participants_json", "raw_ids_json"):
            try:
                d[key[:-5]] = json.loads(d.pop(key) or "[]")
            except Exception:
                d[key[:-5]] = []
                d.pop(key, None)
        out_rows.append(d)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)


def write_cards(conn: sqlite3.Connection, *, day: str | None = None,
                out: str | None = None) -> str:
    write_index(conn)
    text = render_cards(conn, day=day)
    target = Path(out) if out else (_state_dir() / "episode-cards.md")
    if not text:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8")
    return str(target)
