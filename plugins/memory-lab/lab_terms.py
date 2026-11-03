#!/usr/bin/env python3
"""Editable term table for memory-lab.

Own DB only. Never writes soulcore.db.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "memory-lab.db"

SEEDS = [
    # term, kind, weight, action
    ("群聊功能", "meta", 1.0, "penalty"),
    ("私聊功能", "meta", 1.0, "penalty"),
    ("记忆系统", "meta", 0.8, "penalty"),
    ("记忆层", "meta", 0.8, "penalty"),
    ("提示词", "meta", 0.8, "penalty"),
    ("插件", "meta", 0.7, "penalty"),
    ("架构", "meta", 0.7, "penalty"),
    ("检索", "meta", 0.6, "penalty"),
    ("向量", "meta", 0.6, "penalty"),
    ("数据库", "meta", 0.6, "penalty"),
    ("配置", "meta", 0.5, "penalty"),
    ("部署", "meta", 0.5, "penalty"),
    ("代码", "meta", 0.6, "penalty"),
    ("session", "meta", 0.8, "penalty"),
    ("token", "meta", 0.8, "penalty"),
    ("prompt", "meta", 0.8, "penalty"),
    ("api", "meta", 0.6, "penalty"),
    ("dsh", "meta", 0.6, "penalty"),
    ("emotioncore", "meta", 0.6, "penalty"),
    ("soulcore", "meta", 0.6, "penalty"),
    # domain terms; only penalized when the query domain is different
    ("跑团", "entertainment", 0.4, "domain_penalty"),
    ("骰子", "entertainment", 0.4, "domain_penalty"),
    ("表情", "entertainment", 0.3, "domain_penalty"),
    ("二次元", "entertainment", 0.3, "domain_penalty"),
    ("论文", "professional", 0.5, "domain_penalty"),
    ("算法", "professional", 0.5, "domain_penalty"),
    ("实验", "professional", 0.4, "domain_penalty"),
]

DOMAIN_QUERY = {
    "meta": ("功能", "插件", "架构", "提示词", "token", "session", "prompt", "api", "dsh", "emotioncore", "soulcore", "检索", "向量", "数据库", "配置", "部署", "代码"),
    "entertainment": ("跑团", "骰子", "表情", "二次元", "游戏", "整活"),
    "professional": ("论文", "研究", "算法", "实验", "架构", "代码"),
}


def db_path() -> Path:
    return Path(os.environ.get("MEMORY_LAB_DB") or DEFAULT_DB)


def connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p))
    c.row_factory = sqlite3.Row
    ensure(c)
    return c


def ensure(c: sqlite3.Connection) -> None:
    c.execute(
        """CREATE TABLE IF NOT EXISTS lab_terms (
          term TEXT NOT NULL,
          kind TEXT NOT NULL,
          weight REAL NOT NULL DEFAULT 0.5,
          action TEXT NOT NULL DEFAULT 'penalty',
          enabled INTEGER NOT NULL DEFAULT 1,
          note TEXT,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (term, kind)
        )"""
    )
    if c.execute("SELECT COUNT(*) FROM lab_terms").fetchone()[0] == 0:
        from datetime import datetime
        now = datetime.now().astimezone().isoformat()
        c.executemany(
            "INSERT INTO lab_terms(term,kind,weight,action,enabled,note,updated_at) VALUES (?,?,?,?,?,?,?)",
            [(t, k, w, a, 1, "seed", now) for t, k, w, a in SEEDS],
        )
        c.commit()


def terms(c: sqlite3.Connection) -> list[dict]:
    return [dict(x) for x in c.execute("SELECT * FROM lab_terms WHERE enabled=1")]


def query_domain(query: str) -> str:
    q = str(query or "").lower()
    for domain, words in DOMAIN_QUERY.items():
        if any(w.lower() in q for w in words):
            return domain
    return ""


def penalty(c: sqlite3.Connection, text: str, query: str) -> float:
    t = str(text or "").lower()
    qd = query_domain(query)
    total = 0.0
    for row in terms(c):
        if row["term"].lower() not in t:
            continue
        if row["action"] == "penalty":
            if qd != row["kind"]:
                total += float(row["weight"])
        elif row["action"] == "domain_penalty":
            if qd and qd != row["kind"]:
                total += float(row["weight"])
    return round(total, 4)
