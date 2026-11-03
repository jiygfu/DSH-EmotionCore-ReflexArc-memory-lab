#!/usr/bin/env python3
"""Read-only graph projection for memory-lab's 3D view."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

import lab_edges  # noqa: E402


def _appr_avg(main: sqlite3.Connection, raw_ids: list[str]) -> dict:
    if not raw_ids:
        return {"valence": 0.0, "arousal": 0.0}
    marks = ",".join("?" for _ in raw_ids)
    rows = main.execute(
        f"""SELECT a.dimensions_json FROM appraisals a
            WHERE a.id IN (SELECT MAX(id) FROM appraisals WHERE memory_id IN ({marks}) GROUP BY memory_id)""",
        tuple(raw_ids),
    ).fetchall()
    vs = []
    ars = []
    for r in rows:
        try:
            d = json.loads(r["dimensions_json"] or "{}")
            vs.append(float(d.get("valence", 0)))
            ars.append(float(d.get("arousal", 0)))
        except Exception:
            pass
    return {"valence": sum(vs) / len(vs) if vs else 0.0, "arousal": sum(ars) / len(ars) if ars else 0.0}


def graph(main: sqlite3.Connection, *, limit: int = 120) -> dict:
    rows = main.execute(
        """SELECT id,day,start_at,end_at,thread_id,summary,participants_json,importance,unresolved,raw_ids_json
           FROM episodes WHERE COALESCE(status,'open') != 'archived'
           ORDER BY COALESCE(start_at,created_at) DESC LIMIT ?""",
        (max(1, min(500, int(limit))),),
    ).fetchall()
    threads: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        threads[str(r["thread_id"] or r["id"])].append(r)
    nodes = []
    thread_of_memory: dict[str, str] = {}
    for tid, items in threads.items():
        raw_ids: list[str] = []
        for it in items:
            try:
                raw_ids.extend(str(x) for x in json.loads(it["raw_ids_json"] or "[]"))
            except Exception:
                pass
        appr = _appr_avg(main, raw_ids)
        for mid in raw_ids:
            thread_of_memory[mid] = tid
        participants = []
        try:
            for it in items:
                participants.extend(json.loads(it["participants_json"] or "[]"))
        except Exception:
            pass
        nodes.append({
            "id": tid,
            "type": "thread",
            "label": str(items[0]["summary"] or "")[:48],
            "count": len(items),
            "day": items[-1]["day"],
            "importance": max(float(x["importance"] or 0) for x in items),
            "unresolved": max(float(x["unresolved"] or 0) for x in items),
            "valence": round(appr["valence"], 4),
            "arousal": round(appr["arousal"], 4),
            "participants": sorted(set(str(x) for x in participants if x))[:5],
        })
    # Edges from the memory-lab own DB, folded to thread level.
    own = lab_edges.connect()
    try:
        edge_rows = own.execute("SELECT src,dst,decision,weight FROM lab_edges").fetchall()
    finally:
        own.close()
    agg: dict[tuple[str, str], dict] = {}
    for e in edge_rows:
        a = thread_of_memory.get(str(e["src"]))
        b = thread_of_memory.get(str(e["dst"]))
        if not a or not b or a == b:
            continue
        key = (a, b) if a < b else (b, a)
        item = agg.setdefault(key, {"source": key[0], "target": key[1], "weight": 0.0, "decisions": set()})
        item["weight"] += float(e["weight"] or 0)
        item["decisions"].add(str(e["decision"]))
    # Shared-participant edges make the graph navigable even when all
    # boundary edges fall inside a single thread.
    by_person: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        for person in n.get("participants") or []:
            by_person[str(person)].append(str(n["id"]))
    for person, tids in by_person.items():
        uniq = sorted(set(tids))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                a, b = uniq[i], uniq[j]
                key = (a, b) if a < b else (b, a)
                item = agg.setdefault(key, {"source": key[0], "target": key[1], "weight": 0.0, "decisions": set()})
                item["weight"] += 0.15
                item["decisions"].add("same_person")
    edges = []
    for item in agg.values():
        edges.append({
            "source": item["source"],
            "target": item["target"],
            "weight": round(min(1.0, item["weight"] / 3.0), 4),
            "decision": "hard" if "hard" in item["decisions"] else "soft_candidate",
        })
    return {"nodes": nodes, "edges": edges, "threads": len(nodes)}
