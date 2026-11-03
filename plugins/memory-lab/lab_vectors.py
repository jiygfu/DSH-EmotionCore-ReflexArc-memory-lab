#!/usr/bin/env python3
"""Local text embeddings for memory-lab.

Writes only data/memory-lab.db. Reads soulcore.db read-only.
The embedding model is optional: if Ollama/model is unavailable, callers simply
skip the vector channel.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = os.environ.get("MEMORY_LAB_EMBED_MODEL") or "nomic-embed-text"
OLLAMA = os.environ.get("OLLAMA_URL") or "http://127.0.0.1:11434"
OWN_DB = Path(os.environ.get("MEMORY_LAB_DB") or (ROOT / "data" / "memory-lab.db"))


def own() -> sqlite3.Connection:
    OWN_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(OWN_DB))
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE IF NOT EXISTS lab_embeddings (
          memory_id TEXT PRIMARY KEY,
          model TEXT NOT NULL,
          dim INTEGER NOT NULL,
          vector_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )"""
    )
    c.commit()
    return c


def _post(path: str, body: dict, timeout: int = 120):
    req = urllib.request.Request(
        OLLAMA.rstrip("/") + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def embed(texts: list[str], timeout: int = 120) -> list[list[float]]:
    if not texts:
        return []
    try:
        data = _post("/api/embed", {"model": MODEL, "input": texts}, timeout)
        vecs = data.get("embeddings")
        if isinstance(vecs, list) and len(vecs) == len(texts):
            return [[float(x) for x in v] for v in vecs]
    except Exception:
        pass
    out = []
    for text in texts:
        data = _post("/api/embeddings", {"model": MODEL, "prompt": text}, timeout)
        out.append([float(x) for x in data.get("embedding", [])])
    return out


def available() -> bool:
    try:
        req = urllib.request.Request(OLLAMA.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode("utf-8"))
        return any(str(x.get("name") or "").split(":")[0] == MODEL.split(":")[0] for x in data.get("models", []))
    except Exception:
        return False


def embed_missing(main: sqlite3.Connection, *, limit: int = 128) -> dict:
    o = own()
    try:
        done = {r["memory_id"] for r in o.execute("SELECT memory_id FROM lab_embeddings WHERE model=?", (MODEL,))}
        rows = main.execute(
            "SELECT id,text FROM memories WHERE status='active' AND sensitive=0 ORDER BY COALESCE(ts,created_at) DESC"
        ).fetchall()
        todo = [(str(r["id"]), str(r["text"] or "")) for r in rows if str(r["id"]) not in done][: max(1, int(limit))]
        written = 0
        for i in range(0, len(todo), 16):
            batch = todo[i:i + 16]
            vecs = embed([t for _, t in batch])
            now = datetime.now().astimezone().isoformat()
            for (mid, _), vec in zip(batch, vecs):
                if not vec:
                    continue
                o.execute(
                    "INSERT OR REPLACE INTO lab_embeddings(memory_id,model,dim,vector_json,updated_at) VALUES (?,?,?,?,?)",
                    (mid, MODEL, len(vec), json.dumps(vec), now),
                )
                written += 1
            o.commit()
        return {"model": MODEL, "missing_before": len(rows) - len(done), "written": written, "remaining": len(rows) - len(done) - written}
    finally:
        o.close()


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def search(main: sqlite3.Connection, query: str, *, limit: int = 20) -> list[dict]:
    if not query:
        return []
    o = own()
    try:
        if o.execute("SELECT COUNT(*) FROM lab_embeddings WHERE model=?", (MODEL,)).fetchone()[0] == 0:
            return []
        qv = embed([query])[0]
        rows = o.execute("SELECT memory_id,vector_json FROM lab_embeddings WHERE model=?", (MODEL,)).fetchall()
        scored = []
        for r in rows:
            try:
                vec = json.loads(r["vector_json"])
            except Exception:
                continue
            score = _cos(qv, vec)
            if score > 0:
                scored.append((score, r["memory_id"]))
        scored.sort(reverse=True)
        out = []
        for score, mid in scored[: max(1, int(limit))]:
            row = main.execute("SELECT id,text,scope,speaker,ts,person_id,thread_id FROM memories WHERE id=?", (str(mid),)).fetchone()
            if not row:
                continue
            out.append({"memory_id": row["id"], "text": str(row["text"] or ""), "score": round(score, 4),
                        "scope": row["scope"], "speaker": row["speaker"], "ts": row["ts"],
                        "person_id": row["person_id"], "thread_id": row["thread_id"]})
        return out
    except Exception:
        return []
    finally:
        o.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-db", default=str(ROOT / "data" / "soulcore.db"))
    ap.add_argument("--embed", action="store_true")
    ap.add_argument("--query", default="")
    args = ap.parse_args()
    import sqlite3 as _s
    main = _s.connect("file:" + str(Path(args.main_db).resolve()).replace("\\", "/") + "?mode=ro", uri=True)
    main.row_factory = _s.Row
    try:
        if args.embed:
            print(embed_missing(main))
        if args.query:
            print(json.dumps(search(main, args.query), ensure_ascii=False, indent=2))
    finally:
        main.close()
