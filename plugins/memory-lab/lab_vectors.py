#!/usr/bin/env python3
"""Local Chinese embeddings for memory-lab (S6).

Model: BAAI/bge-small-zh-v1.5, exported to ONNX (512 维, 4 层, ~95 MB).
Runtime: onnxruntime CPU + numpy —— 已经是运行时自带的两个包，不新增依赖。

写入只发生在 data/memory-lab.db 的 `mem_vectors` 表（向量是派生索引，不是事实），
soulcore.db 仍然只读。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = Path(os.environ.get("MEMORY_LAB_MODEL_DIR") or (ROOT / "plugins" / "memory-lab" / "models" / "bge-small-zh-v1.5"))
MODEL = os.environ.get("MEMORY_LAB_EMBED_MODEL") or "bge-small-zh-v1.5"
DIM = 512
MAX_LEN = 256
OWN_DB = Path(os.environ.get("MEMORY_LAB_DB") or (ROOT / "data" / "memory-lab.db"))

# BGE 中文检索的官方建议前缀，但那是为"短 query 检索长文章"设计的。
# 我们的"文章"是几十字的聊天片段，实测加前缀反而把分数压平、相关性变差
# （同一个 query：带 0.50，不带 0.58；且不带时榜首才是真正相关的那条）。
# 所以默认不加，需要时用 MEMORY_LAB_QUERY_PREFIX=1 打开。
QUERY_PREFIX = os.environ.get("MEMORY_LAB_QUERY_PREFIX") or ""
if str(QUERY_PREFIX).strip() in {"1", "true", "on"}:
    QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

_SESSION = None
_TOKENIZER = None
_CACHE: dict = {"n": -1, "ids": [], "mat": None}


# ── tokenizer（BERT WordPiece；不想为它引入 transformers）────────────────
def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def _is_punct(ch: str) -> bool:
    return unicodedata.category(ch).startswith("P")


class BertTokenizer:
    def __init__(self, vocab_path: Path):
        self.vocab: dict[str, int] = {}
        with open(vocab_path, "r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                self.vocab[line.rstrip("\n")] = idx
        self.unk = self.vocab.get("[UNK]", 100)
        self.cls = self.vocab.get("[CLS]", 101)
        self.sep = self.vocab.get("[SEP]", 102)
        self.pad = self.vocab.get("[PAD]", 0)

    def _basic(self, text: str) -> list[str]:
        buf: list[str] = []
        for ch in text:
            if ch.isspace() or ch == "\u3000":
                buf.append(" ")
            elif _is_cjk(ch) or _is_punct(ch):
                buf.append(" ")
                buf.append(ch)
                buf.append(" ")
            else:
                buf.append(ch)
        return "".join(buf).split()

    def _wordpiece(self, token: str) -> list[int]:
        if len(token) > 100:
            return [self.unk]
        pieces: list[int] = []
        start = 0
        while start < len(token):
            end = len(token)
            found = None
            while start < end:
                piece = token[start:end]
                if start > 0:
                    piece = "##" + piece
                if piece in self.vocab:
                    found = piece
                    break
                end -= 1
            if found is None:
                return [self.unk]
            pieces.append(self.vocab[found])
            start = end
        return pieces

    def encode(self, text: str, max_len: int = MAX_LEN) -> tuple[list[int], list[int]]:
        ids = [self.cls]
        for token in self._basic(str(text or "")):
            ids.extend(self._wordpiece(token))
            if len(ids) >= max_len - 1:
                break
        ids = ids[: max_len - 1]
        ids.append(self.sep)
        return ids, [1] * len(ids)


def tokenizer() -> BertTokenizer:
    global _TOKENIZER
    if _TOKENIZER is None:
        _TOKENIZER = BertTokenizer(MODEL_DIR / "vocab.txt")
    return _TOKENIZER


def session():
    """懒加载 ONNX 会话；线程数压到 2，别跟 QQ 主进程抢 CPU。"""
    global _SESSION
    if _SESSION is None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        _SESSION = ort.InferenceSession(
            str(MODEL_DIR / "model.onnx"), sess_options=opts, providers=["CPUExecutionProvider"]
        )
    return _SESSION


def available() -> bool:
    if not (MODEL_DIR / "model.onnx").exists() or not (MODEL_DIR / "vocab.txt").exists():
        return False
    try:
        session()
        return True
    except Exception:
        return False


# ── 编码 ────────────────────────────────────────────────────────────────
def encode(texts: list[str], *, query: bool = False, batch: int = 16) -> "list[list[float]]":
    """CLS pooling + L2 归一化（BGE 的官方用法）。返回 Python list，方便调用方直接存 BLOB。"""
    import numpy as np

    if not texts:
        return []
    tok = tokenizer()
    sess = session()
    prefix = QUERY_PREFIX if query else ""
    out: list[list[float]] = []
    for i in range(0, len(texts), max(1, batch)):
        chunk = [prefix + str(t) for t in texts[i : i + batch]]
        seqs = [tok.encode(t) for t in chunk]
        width = max(len(s[0]) for s in seqs)
        ids = np.zeros((len(seqs), width), dtype=np.int64)
        mask = np.zeros((len(seqs), width), dtype=np.int64)
        for row, (tokens, _) in enumerate(seqs):
            ids[row, : len(tokens)] = tokens
            mask[row, : len(tokens)] = 1
        hidden = sess.run(
            ["last_hidden_state"],
            {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)},
        )[0]
        cls = hidden[:, 0, :].astype(np.float32)
        norm = np.linalg.norm(cls, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        out.extend((cls / norm).tolist())
    return out


def pack(vec: list[float]) -> bytes:
    import numpy as np

    return np.asarray(vec, dtype="<f4").tobytes()


def unpack(blob: bytes) -> "list[float]":
    import numpy as np

    return np.frombuffer(blob, dtype="<f4").astype(np.float32).tolist()


# ── 存储 ────────────────────────────────────────────────────────────────
def own() -> sqlite3.Connection:
    OWN_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(OWN_DB))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS mem_vectors (
          memory_id TEXT PRIMARY KEY,
          model TEXT NOT NULL,
          dim INTEGER NOT NULL,
          vec BLOB NOT NULL,
          text_hash TEXT,
          updated_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vec_model ON mem_vectors(model)")
    conn.commit()
    return conn


def _hash(text: str) -> str:
    return hashlib.sha1(str(text or "")[:512].encode("utf-8")).hexdigest()


def embed_missing(main: sqlite3.Connection, *, limit: int = 256, batch: int = 16) -> dict:
    """把还没向量化的记忆补上；只处理 active 且非 sensitive。"""
    o = own()
    try:
        done = {r[0] for r in o.execute("SELECT memory_id FROM mem_vectors WHERE model=?", (MODEL,))}
        rows = main.execute(
            """SELECT id, text FROM memories
               WHERE status='active' AND COALESCE(sensitive,0)=0
               ORDER BY COALESCE(ts, created_at) DESC"""
        ).fetchall()
        todo = [(str(r["id"]), str(r["text"] or "")) for r in rows if str(r["id"]) not in done]
        batch = max(1, int(batch))
        todo = todo[: max(1, int(limit))]
        written = 0
        now = datetime.now().astimezone().isoformat()
        for i in range(0, len(todo), batch):
            part = todo[i : i + batch]
            vecs = encode([t for _, t in part], batch=batch)
            for (mid, text), vec in zip(part, vecs):
                if not vec:
                    continue
                o.execute(
                    "INSERT OR REPLACE INTO mem_vectors(memory_id,model,dim,vec,text_hash,updated_at) VALUES (?,?,?,?,?,?)",
                    (mid, MODEL, len(vec), pack(vec), _hash(text), now),
                )
                written += 1
            o.commit()
        return {"model": MODEL, "missing_before": len(rows) - len(done), "written": written,
                "remaining": max(0, len(rows) - len(done) - written)}
    finally:
        o.close()


def _matrix(conn: sqlite3.Connection):
    """全部向量读进内存做暴力余弦；行数变了才重建。1100 行 × 512 维 ≈ 2.3 MB。"""
    import numpy as np

    n = conn.execute("SELECT COUNT(*) FROM mem_vectors WHERE model=?", (MODEL,)).fetchone()[0]
    if _CACHE["n"] == n and _CACHE["mat"] is not None:
        return _CACHE["ids"], _CACHE["mat"]
    ids: list[str] = []
    rows: list[bytes] = []
    for row in conn.execute("SELECT memory_id, vec FROM mem_vectors WHERE model=?", (MODEL,)):
        ids.append(str(row["memory_id"]))
        rows.append(row["vec"])
    mat = np.vstack([np.frombuffer(b, dtype="<f4") for b in rows]).astype(np.float32) if rows else None
    _CACHE.update({"n": n, "ids": ids, "mat": mat})
    return ids, mat


def search(main: sqlite3.Connection, query: str, *, limit: int = 20, min_score: float = 0.0) -> list[dict]:
    if not query or not available():
        return []
    o = own()
    try:
        ids, mat = _matrix(o)
        if mat is None or not ids:
            return []
        import numpy as np

        qv = np.asarray(encode([query], query=True)[0], dtype=np.float32)
        scores = mat @ qv
        top = min(len(ids), max(1, int(limit)) * 4)
        idx = np.argpartition(-scores, top - 1)[:top]
        idx = idx[np.argsort(-scores[idx])]
        out: list[dict] = []
        for i in idx:
            score = float(scores[i])
            if score <= min_score:
                continue
            row = main.execute(
                "SELECT id,text,scope,speaker,ts,person_id,thread_id FROM memories WHERE id=?",
                (str(ids[i]),),
            ).fetchone()
            if not row:
                continue
            out.append({"memory_id": row["id"], "text": str(row["text"] or ""), "score": round(score, 4),
                        "scope": row["scope"], "speaker": row["speaker"], "ts": row["ts"],
                        "person_id": row["person_id"], "thread_id": row["thread_id"]})
            if len(out) >= max(1, int(limit)):
                break
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
    ap.add_argument("--limit", type=int, default=256)
    ap.add_argument("--query", default="")
    args = ap.parse_args()
    main = sqlite3.connect("file:" + str(Path(args.main_db).resolve()).replace("\\", "/") + "?mode=ro", uri=True)
    main.row_factory = sqlite3.Row
    try:
        if args.embed:
            print(json.dumps(embed_missing(main, limit=args.limit), ensure_ascii=False))
        if args.query:
            print(json.dumps(search(main, args.query), ensure_ascii=False, indent=2))
    finally:
        main.close()
