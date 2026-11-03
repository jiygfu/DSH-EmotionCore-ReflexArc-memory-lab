#!/usr/bin/env python3
"""memory-lab — read-only multi-axis recall prototype.

This is deliberately NOT wired into EmotionCore, L5, ReflexArc, or the QQ
session. It opens soulcore.db read-only and prints a comparison between:

  baseline: existing retrieval.search_memories (FTS / 2-gram)
  lab:      baseline seeds + same-thread / same-person / appraisal expansion

No writes. No plugin activation. Safe to delete.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from soulcore import retrieval  # noqa: E402

import lab_terms  # noqa: E402
import lab_config  # noqa: E402
import lab_edges  # noqa: E402
import lab_vectors  # noqa: E402

THREAD_EXPAND = 2
PERSON_EXPAND = 2
EMOTION_EXPAND = 1
MAX_EXPANDED = 3

DIMENSIONS = ("security", "trust", "self_efficacy", "caution", "sociability", "openness", "valence", "arousal")


def connect_ro(db_path: str) -> sqlite3.Connection:
    uri = "file:" + str(Path(db_path).resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _appraisal(conn: sqlite3.Connection, memory_id: str) -> dict[str, Any]:
    row = conn.execute(
        """SELECT dimensions_json, unresolved, confidence FROM appraisals
           WHERE memory_id=? ORDER BY id DESC LIMIT 1""",
        (memory_id,),
    ).fetchone()
    if not row:
        return {}
    try:
        dims = json.loads(row["dimensions_json"] or "{}")
    except Exception:
        dims = {}
    return {"dims": dims, "unresolved": float(row["unresolved"] or 0), "confidence": float(row["confidence"] or 0)}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys = [k for k in DIMENSIONS if k in a or k in b]
    if not keys:
        return 0.0
    va = [float(a.get(k, 0.0)) for k in keys]
    vb = [float(b.get(k, 0.0)) for k in keys]
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(x * x for x in vb))
    if not na or not nb:
        return 0.0
    return sum(x * y for x, y in zip(va, vb)) / (na * nb)


def _text_overlap(a: str, b: str) -> float:
    sa = set("".join(str(a or "").split()).lower())
    sb = set("".join(str(b or "").split()).lower())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


FEATURE_TERMS = (
    "功能", "插件", "架构", "提示词", "prompt", "token", "session", "会话",
    "记忆层", "记忆系统", "检索", "向量", "模型", "api", "dsh", "emotioncore",
    "soulcore", "配置", "部署", "代码", "调用", "工具", "日志", "数据库",
)
META_QUERY = re.compile(r"(功能|插件|架构|提示词|prompt|token|session|代码|模型|检索|向量|dsh|emotioncore|soulcore|配置|部署|数据库|工具)", re.I)


def _meta_score(text: str) -> int:
    t = str(text or "").lower()
    return sum(1 for x in FEATURE_TERMS if x in t)


CODE_TERMS = ("prompt", "token", "session", "api", "dsh", "emotioncore", "soulcore", "sqlite", "json")
META_SIGNALS = ("功能", "插件", "架构", "提示词", "模型", "检索", "向量", "配置", "部署", "代码", "数据库", "工具", "日志")
STRONG_META = (
    "群聊功能", "私聊功能", "记忆系统", "记忆层", "记忆分层", "提示词", "插件",
    "架构", "session", "token", "prompt", "api", "dsh", "emotioncore", "soulcore",
    "sqlite", "数据库", "检索", "向量", "配置", "部署", "代码",
)
CONTENT_SIGNALS = ("今天", "昨天", "刚才", "那次", "当时", "觉得", "感觉", "开心", "难过", "生气", "喜欢", "讨厌", "你", "我", "他", "她")


def _classify(text: str) -> str:
    t = str(text or "").lower()
    meta = _meta_score(t)
    code = sum(1 for x in CODE_TERMS if x in t)
    if any(x in t for x in STRONG_META):
        return "meta"
    if code and (meta or "system" in t or "模型" in t or "插件" in t):
        return "meta"
    if meta >= 2:
        return "meta"
    if meta >= 1 and not any(x in t for x in CONTENT_SIGNALS):
        return "meta"
    return "content"


def _query_mode(query: str) -> str:
    q = str(query or "")
    return "meta" if _meta_score(q) >= 1 else "content"


def _scope_of(query: str) -> str:
    q = str(query or "")
    is_group = bool(re.search(r"(群聊|群里|群内|那个群)", q))
    is_private = bool(re.search(r"(私聊|私信)", q))
    if is_group and not is_private:
        return "group"
    if is_private and not is_group:
        return "private"
    return ""


def _row(conn: sqlite3.Connection, memory_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()


def _public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "memory_id": row["id"],
        "ts": row["ts"],
        "speaker": row["speaker"],
        "scope": row["scope"],
        "person_id": row["person_id"],
        "thread_id": row["thread_id"],
        "text": str(row["text"] or "")[:180],
    }


def baseline(conn: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
    return retrieval.search_memories(conn, query, limit=limit)


def lab_recall(conn: sqlite3.Connection, query: str, *, limit: int = 8, expand: int = 24) -> dict[str, Any]:
    seeds = baseline(conn, query, limit=max(4, limit))
    if not seeds:
        return {"query": query, "seeds": [], "items": [], "expanded": []}

    mode_meta = _query_mode(query) == "meta"
    scope_filter = _scope_of(query)
    if scope_filter:
        seeds = [x for x in seeds if str(x.get("scope") or "") == scope_filter]
    if not mode_meta:
        seeds = [x for x in seeds if _classify(x.get("text", "")) == "content"]
    seed_ids = [str(x["id"]) for x in seeds]
    seed_appraisals = {sid: _appraisal(conn, sid) for sid in seed_ids}
    candidates: dict[str, dict[str, Any]] = {}
    for item in seeds:
        candidates[str(item["id"])] = {
            "memory_id": item["id"],
            "score": float(item.get("score") or 0) + 1.0,
            "why": ["baseline"],
            "row": _row(conn, str(item["id"])),
        }

    # Same-thread and same-person expansion from each seed. Read-only.
    for sid in seed_ids:
        seed = _row(conn, sid)
        if not seed:
            continue
        thread = str(seed["thread_id"] or "")
        person = str(seed["person_id"] or "")
        if thread and (mode_meta or _meta_score(seed["text"]) < 2):
            for row in conn.execute(
                "SELECT * FROM memories WHERE thread_id=? AND status='active' AND sensitive=0 ORDER BY COALESCE(ts,created_at) DESC LIMIT ?",
                (thread, min(expand, THREAD_EXPAND)),
            ):
                if str(row["id"]) in seed_ids:
                    continue
                if scope_filter and str(row["scope"] or "") != scope_filter:
                    continue
                if not mode_meta and _classify(row["text"]) != "content":
                    continue
                ent = candidates.setdefault(str(row["id"]), {"memory_id": row["id"], "score": 0.0, "why": [], "row": row})
                if "same_thread" not in ent["why"]:
                    ent["why"].append("same_thread")
                ent["score"] += 0.20
        if person:
            for row in conn.execute(
                "SELECT * FROM memories WHERE person_id=? AND status='active' AND sensitive=0 ORDER BY COALESCE(ts,created_at) DESC LIMIT ?",
                (person, min(expand, PERSON_EXPAND)),
            ):
                if str(row["id"]) in seed_ids:
                    continue
                if str(row["thread_id"] or "") != thread and _text_overlap(query, row["text"]) < 0.18:
                    continue
                if scope_filter and str(row["scope"] or "") != scope_filter:
                    continue
                if not mode_meta and _classify(row["text"]) != "content":
                    continue
                ent = candidates.setdefault(str(row["id"]), {"memory_id": row["id"], "score": 0.0, "why": [], "row": row})
                if "same_person" not in ent["why"]:
                    ent["why"].append("same_person")
                ent["score"] += 0.10

    # Emotion-axis similarity to the strongest seed.
    strongest = max(seed_ids, key=lambda x: float(seed_appraisals.get(x, {}).get("confidence") or 0))
    base_vec = seed_appraisals.get(strongest, {}).get("dims") or {}
    for sid in seed_ids:
        appr = seed_appraisals.get(sid, {}).get("dims") or {}
        if not appr:
            continue
        sid_row = _row(conn, sid)
        person_for_emotion = str(sid_row["person_id"] or "") if sid_row else ""
        if not person_for_emotion:
            continue
        for row in conn.execute(
            "SELECT id FROM memories WHERE person_id=? AND status='active' AND sensitive=0 LIMIT ?",
            (person_for_emotion, EMOTION_EXPAND),
        ):
            rid = str(row["id"])
            if rid in seed_ids:
                continue
            ra = _appraisal(conn, rid)
            sim = _cosine(base_vec, ra.get("dims") or {})
            if sim <= 0.3:
                continue
            candidate_row = _row(conn, rid)
            if not candidate_row:
                continue
            same_thread_as_seed = str(candidate_row["thread_id"] or "") == str((sid_row["thread_id"] if sid_row else "") or "")
            if not same_thread_as_seed and _text_overlap(query, candidate_row["text"]) < 0.18:
                continue
            if scope_filter and str(candidate_row["scope"] or "") != scope_filter:
                continue
            if not mode_meta and _classify(candidate_row["text"]) != "content":
                continue
            ent = candidates.setdefault(rid, {"memory_id": rid, "score": 0.0, "why": [], "row": candidate_row})
            if "emotion_near" not in ent["why"]:
                ent["why"].append("emotion_near")
            ent["score"] += 0.15 * sim

    items = []
    tc = lab_terms.connect()
    try:
        for ent in candidates.values():
            row = ent.get("row")
            if not row:
                continue
            pen = lab_terms.penalty(tc, row["text"], query)
            items.append({**_public(row), "score": round(float(ent["score"]) - 0.25 * pen, 4), "why": ent["why"], "meta_score": _meta_score(row["text"]), "kind": _classify(row["text"]), "term_penalty": pen})
    finally:
        tc.close()
    items.sort(key=lambda x: x["score"], reverse=True)
    return {
        "query": query,
        "seeds": seeds,
        "items": items[:limit],
        "expanded": [x for x in items if "baseline" not in x["why"]][:MAX_EXPANDED],
    }


RRF_K = 60
SOFT_CUE = re.compile(r"(上次|那次|之前|后来|接着|后续|然后|同一件|这件事|那件事|后来呢)")


def _dedupe(ids: list[str]) -> list[str]:
    out = []
    seen = set()
    for x in ids:
        x = str(x)
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def rrf_recall(conn: sqlite3.Connection, query: str, *, limit: int = 8) -> dict[str, Any]:
    """RRF over FTS + same-thread + same-person + emotion-near lists.

    No embedding. No writes. This is a ranking experiment, not a replacement
    for the production recall path.
    """
    seeds = baseline(conn, query, max(6, limit))
    mode_meta = _query_mode(query) == "meta"
    scope_filter = _scope_of(query)
    if scope_filter:
        seeds = [x for x in seeds if str(x.get("scope") or "") == scope_filter]
    if not mode_meta:
        seeds = [x for x in seeds if _classify(x.get("text", "")) == "content"]
    if not seeds:
        return {"query": query, "items": [], "lists": {}}
    lists: dict[str, list[str]] = {"fts": [str(x["id"]) for x in seeds]}
    rows_by_id: dict[str, sqlite3.Row] = {}
    try:
        vec_hits = lab_vectors.search(conn, query, limit=8) if lab_config.read().get("vectorEnabled") is True else []
    except Exception:
        vec_hits = []
    if vec_hits:
        lists["vector"] = [str(x["memory_id"]) for x in vec_hits]
    edge_conn = lab_edges.connect()
    try:
        if (mode_meta or SOFT_CUE.search(query)):
          for item in seeds:
            for n in lab_edges.neighbors(edge_conn, str(item["id"]), limit=4):
                nrow = _row(conn, str(n["dst"]))
                if not nrow:
                    continue
                if scope_filter and str(nrow["scope"] or "") != scope_filter:
                    continue
                if not mode_meta and _classify(nrow["text"]) != "content":
                    continue
                lists.setdefault("soft_edge", []).append(str(n["dst"]))
    finally:
        edge_conn.close()
    for item in seeds:
        row = _row(conn, str(item["id"]))
        if not row:
            continue
        rows_by_id[str(row["id"])] = row
        thread = str(row["thread_id"] or "")
        person = str(row["person_id"] or "")
        if thread and (mode_meta or _meta_score(row["text"]) < 1):
            lists.setdefault("thread", []).extend(
                str(x["id"]) for x in conn.execute(
                    "SELECT id,scope,text FROM memories WHERE thread_id=? AND status='active' AND sensitive=0 ORDER BY COALESCE(ts,created_at) DESC LIMIT 4",
                    (thread,),
                )
                if (not scope_filter or str(x["scope"] or "") == scope_filter)
                and (mode_meta or _classify(x["text"] or "") == "content")
            )
        if person:
            lists.setdefault("person", []).extend(
                str(x["id"]) for x in conn.execute(
                    "SELECT id,scope,text FROM memories WHERE person_id=? AND status='active' AND sensitive=0 ORDER BY COALESCE(ts,created_at) DESC LIMIT 4",
                    (person,),
                )
                if (not scope_filter or str(x["scope"] or "") == scope_filter)
                and (mode_meta or _classify(x["text"] or "") == "content")
            )
            seed_appr = _appraisal(conn, str(row["id"]))
            scored = []
            for x in conn.execute(
                "SELECT id,scope,text FROM memories WHERE person_id=? AND status='active' AND sensitive=0 LIMIT 20",
                (person,),
            ):
                rid = str(x["id"])
                if scope_filter and str(x["scope"] or "") != scope_filter:
                    continue
                if not mode_meta and _classify(x["text"] or "") != "content":
                    continue
                sim = _cosine(seed_appr.get("dims") or {}, _appraisal(conn, rid).get("dims") or {})
                if sim >= 0.3:
                    scored.append((sim, rid))
            scored.sort(reverse=True)
            lists.setdefault("emotion", []).extend(rid for _, rid in scored[:4])
    weights = {"fts": 1.0, "thread": 0.4, "person": 0.2, "emotion": 0.3, "soft_edge": 0.35, "vector": 0.8}
    scores: dict[str, float] = {}
    for name, ids in lists.items():
        for rank, mid in enumerate(_dedupe(ids), 1):
            row = rows_by_id.get(mid) or _row(conn, mid)
            if not row:
                continue
            rows_by_id[mid] = row
            scores[mid] = scores.get(mid, 0.0) + weights.get(name, 0.2) / (RRF_K + rank)
    items = []
    tc = lab_terms.connect()
    try:
        for mid, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
            row = rows_by_id[mid]
            axes = [name for name, ids in lists.items() if mid in _dedupe(ids)]
            pen = lab_terms.penalty(tc, row["text"], query)
            items.append({**_public(row), "rrf_score": round(score, 6), "rrf_adjusted": round(score - 0.002 * pen, 6), "term_penalty": pen, "axes": axes, "meta_score": _meta_score(row["text"]), "kind": _classify(row["text"])})
    finally:
        tc.close()
    items.sort(key=lambda x: x["rrf_adjusted"], reverse=True)
    return {"query": query, "items": items[: max(1, int(limit))], "lists": {k: _dedupe(v)[:8] for k, v in lists.items()}}


def write_review_sheet(conn: sqlite3.Connection, *, limit: int = 5, out: str = "") -> Path:
    queries = [
        "潜意识 分层", "骰子 失败", "群聊 记忆", "未完成 事件",
        "人格 改动", "身体 状态", "记忆 归档", "那个人 烦",
    ]
    data = {
        "version": 4,
        "instructions": "Debug-only human review. Mark relevant true/false; preference baseline/rrf/tie.",
        "queries": [],
    }
    for q in queries:
        b = baseline(conn, q, limit)
        r = rrf_recall(conn, q, limit=limit)
        data["queries"].append({
            "query": q,
            "baseline": [{**x, "relevant": None, "kind": _classify(x.get("text", "")), "meta_score": _meta_score(x.get("text", ""))} for x in b],
            "rrf": [{**x, "relevant": None} for x in r["items"]],
            "preference": None,
            "note": "",
        })
    target = Path(out) if out else ROOT / "reports" / "rrf-human-review-debug.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "soulcore.db"))
    ap.add_argument("--query", default="")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mode", choices=["additive","rrf"], default="additive")
    ap.add_argument("--review", action="store_true", help="generate a debug review sheet if humanReview is enabled")
    ap.add_argument("--review-out", default="")
    args = ap.parse_args()
    if not args.query and not args.review:
        print("--query is required unless --review is used")
        return 2
    conn = connect_ro(args.db)
    try:
        if args.review:
            if not lab_config.human_review_enabled():
                print("humanReview=false; enable it in plugins/memory-lab/config.json")
                return 0
            out = write_review_sheet(conn, limit=max(4, args.limit), out=args.review_out)
            print(out)
            return 0
        base = baseline(conn, args.query, max(4, args.limit))
        lab = rrf_recall(conn, args.query, limit=max(4, args.limit)) if args.mode == "rrf" else lab_recall(conn, args.query, limit=max(4, args.limit))
    finally:
        conn.close()
    out = {
        "query": args.query,
        "baseline": base,
        "lab": lab,
        "baseline_ids": [x["id"] for x in base],
        "lab_ids": [x["memory_id"] for x in lab["items"]],
        "overlap": len(set(x["id"] for x in base) & set(x["memory_id"] for x in lab["items"])),
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"query={args.query}")
        print("baseline:", [x["id"] for x in base])
        print("lab     :", [x["memory_id"] for x in lab["items"]])
        print("expanded:", [x for x in lab["expanded"] if "baseline" not in x["why"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
