#!/usr/bin/env python3
"""S7 冷热分层：把"又老又没被想起"的记忆压进冷库，热库只留一行摘要。

三条硬规矩（按你的决定）：
1. **不删**。原文 zlib 压进 `mem_cold`，随时能捞回来。
2. **主人相关的知识性记忆永不归档**（身份/偏好/约定/关系转折/明确要求）。
3. **当日临时测试刷屏照常归档**——这正是最该瘦身的部分，不因为它出自主人就豁免。

冷库也要索引：`memory_id` 主键 + `created_at` 索引。
"""

from __future__ import annotations

import json
import os
import sqlite3
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data" / "archive-config.json"

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "archiveAfterDays": 30,      # 多久没被想起才算"老"
    "maxImportance": 0.15,       # 重要度高于这个就留着
    "maxTriggers": 1,            # 被用过两次以上说明还有用
    "protectMinChars": 200,      # 长消息当有信息量，不按"老"归档
    # 主人 QQ 不进仓库：由 data/archive-config.json 的 ownerId 覆盖（该文件被 .gitignore 排除）。
    # 留空 = 不做"主人知识"保护；本地部署必须在 data/archive-config.json 里配好。
    "ownerId": "",
    "testBurst": False,          # 当日测试刷屏分支（默认关，跑一段看误伤再说）
    "testBurstDays": 3,          # 至少隔几天才动
    "testBurstMinPerDay": 80,    # 当天条数达到这个量级才算刷屏
    "batch": 200,
}

# 知识性标记：命中就不再按"老"归档（只在主人说的那条上生效）
KNOWLEDGE_MARKERS = (
    "我叫", "我的名字", "生日", "喜欢", "讨厌", "习惯", "约定", "说好", "答应",
    "记住", "别忘了", "帮我记", "记一下", "以后", "每次", "上班", "学校", "工作",
    "住在", "家里", "我妈", "我爸", "老公", "老婆", "孩子", "叫我", "别叫我",
)

SUMMARY_LIMIT = 24      # 只留一点点线索，够她认出"这是哪件事"就行
SUMMARY_SUFFIX = "…〔归档〕"


def load() -> dict[str, Any]:
    """配置热读：改完下一轮生效。"""
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    if not key.startswith("_") and key in cfg:
                        cfg[key] = value
    except Exception:
        pass
    return cfg


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def ensure_schema(conn: sqlite3.Connection) -> None:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(memories)")}
    if "archived_at" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN archived_at TEXT")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mem_cold (
          memory_id TEXT PRIMARY KEY,
          blob BLOB NOT NULL,
          codec TEXT NOT NULL DEFAULT 'zlib',
          text_len INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cold_created ON mem_cold(created_at);
        CREATE INDEX IF NOT EXISTS idx_mem_archived ON memories(archived_at) WHERE status='archived';
        """
    )
    conn.commit()


# ── 判定 ────────────────────────────────────────────────────────────────
def _days_since(stamp: str | None) -> float:
    text = str(stamp or "").strip()
    if not text:
        return 1e6
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        try:
            moment = datetime.fromisoformat(text[:19])
        except Exception:
            return 1e6
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds() / 86400.0


def is_owner_knowledge(row: sqlite3.Row, owner_id: str) -> bool:
    """主人说的 + 带知识性标记 = 永不归档。"""
    person = str(row["person_id"] or "")
    if person != owner_id:
        return False
    text = str(row["text"] or "")
    return any(mark in text for mark in KNOWLEDGE_MARKERS)


def protected_reason(row: sqlite3.Row, cfg: dict[str, Any], open_threads: set[str] | None = None) -> str:
    """返回不能归档的原因（空字符串 = 可以归档）。

    `open_threads` 只放**还开着**的话题；552 条记忆带 thread_id，但 thread_loops 里
    只有 10 个话题、其中一些是 closing——不能拿"有 thread_id"就当保护伞。
    """
    if str(row["status"] or "") != "active":
        return f"status={row['status']}"
    if str(row["source_kind"] or "dialog") != "dialog":
        return "非对话来源"
    if str(row["scope"] or "") in ("pet", "skill"):
        return "身体/技能层"
    if float(row["importance"] or 0) >= 0.5:
        return "importance 高"
    if open_threads and str(row["thread_id"] or "") in open_threads:
        return "挂在未收尾话题上"
    if int(row["trigger_count"] or 0) > int(cfg["maxTriggers"]):
        return "被想起过多次"
    if len(str(row["text"] or "")) >= int(cfg["protectMinChars"]):
        return "长文（有信息量）"
    if is_owner_knowledge(row, str(cfg["ownerId"])):
        return "主人知识"
    return ""


def _open_threads(conn: sqlite3.Connection) -> set[str]:
    try:
        rows = conn.execute(
            "SELECT thread_id FROM thread_loops WHERE status IN ('open','waiting','paused')"
        ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(r[0]) for r in rows if r[0]}


def is_stale(row: sqlite3.Row, cfg: dict[str, Any]) -> bool:
    age = _days_since(row["ts"] or row["created_at"])
    if age < float(cfg["archiveAfterDays"]):
        return False
    if float(row["importance"] or 0) > float(cfg["maxImportance"]):
        return False
    last = row["last_triggered_at"]
    if last and _days_since(last) < float(cfg["archiveAfterDays"]):
        return False
    return True


def _burst_days(conn: sqlite3.Connection) -> set[str]:
    """同一天条数超阈值的那些天（测试刷屏）。"""
    cfg = load()
    rows = conn.execute(
        "SELECT substr(ts,1,10) d, COUNT(*) n FROM memories WHERE status='active' GROUP BY d"
    ).fetchall()
    return {str(r[0]) for r in rows if int(r[1] or 0) >= int(cfg["testBurstMinPerDay"])}


def plan(conn: sqlite3.Connection, *, limit: int = 0) -> dict[str, Any]:
    """只算不写：谁会进冷库、谁被保护、为什么。"""
    cfg = load()
    bursts = _burst_days(conn) if cfg.get("testBurst") else set()
    open_threads = _open_threads(conn)
    rows = conn.execute(
        "SELECT * FROM memories WHERE status='active' ORDER BY COALESCE(ts, created_at)"
    ).fetchall()
    picked: list[dict[str, Any]] = []
    kept: dict[str, int] = {}
    for row in rows:
        reason = protected_reason(row, cfg, open_threads)
        if reason:
            kept[reason] = kept.get(reason, 0) + 1
            continue
        stale = is_stale(row, cfg)
        burst = bool(bursts) and str(row["ts"] or "")[:10] in bursts and \
            _days_since(row["ts"]) >= float(cfg["testBurstDays"])
        if not (stale or burst):
            kept["还新"] = kept.get("还新", 0) + 1
            continue
        picked.append({
            "memory_id": row["id"],
            "ts": row["ts"],
            "why": "陈旧" if stale else "测试刷屏",
            "text": str(row["text"] or "")[:60],
        })
        if limit and len(picked) >= int(limit):
            break
    return {"cfg": cfg, "total_active": len(rows), "to_archive": len(picked), "kept": kept,
            "burst_days": sorted(bursts), "items": picked}


# ── 执行 ────────────────────────────────────────────────────────────────
def _summary(text: str) -> str:
    body = str(text or "").strip()
    if len(body) <= SUMMARY_LIMIT:
        return body + SUMMARY_SUFFIX
    return body[:SUMMARY_LIMIT] + SUMMARY_SUFFIX


def run(conn: sqlite3.Connection, *, limit: int = 200, dry_run: bool = False) -> dict[str, Any]:
    ensure_schema(conn)
    data = plan(conn, limit=limit)
    items = data["items"]
    if dry_run or not items:
        return {"dry_run": dry_run, **{k: data[k] for k in ("total_active", "to_archive", "kept", "burst_days")},
                "written": 0, "sample": items[:5]}

    now = _now()
    written = 0
    saved_bytes = 0
    for item in items:
        row = conn.execute("SELECT text FROM memories WHERE id=?", (item["memory_id"],)).fetchone()
        if not row:
            continue
        original = str(row["text"] or "")
        raw = original.encode("utf-8")
        blob = zlib.compress(raw, 9)
        # 短句压完反而更大（zlib 头尾开销），那就存原样——别为了"压缩"让库变大
        codec = "zlib" if len(blob) < len(raw) else "raw"
        if codec == "raw":
            blob = raw
        saved_bytes += len(raw) - len(blob)
        conn.execute(
            "INSERT OR REPLACE INTO mem_cold(memory_id, blob, codec, text_len, created_at) VALUES (?,?,?,?,?)",
            (item["memory_id"], blob, codec, len(original), now),
        )
        conn.execute(
            "UPDATE memories SET text=?, status='archived', archived_at=?, updated_at=? WHERE id=?",
            (_summary(original), now, now, item["memory_id"]),
        )
        written += 1
    conn.commit()
    return {"dry_run": False, "total_active": data["total_active"], "to_archive": data["to_archive"],
            "written": written, "kept": data["kept"], "saved_bytes": saved_bytes}


def text_of(conn: sqlite3.Connection, memory_id: str, fallback: str = "") -> str:
    """深挖用：归档的就从冷库解压原文（raw 存的原样返回）。"""
    row = conn.execute("SELECT blob, codec FROM mem_cold WHERE memory_id=?", (str(memory_id),)).fetchone()
    if not row:
        return fallback
    try:
        blob = bytes(row["blob"])
        codec = str(row["codec"] or "zlib")
        if codec == "raw":
            return blob.decode("utf-8")
        if codec == "zlib":
            return zlib.decompress(blob).decode("utf-8")
        return fallback
    except Exception:
        return fallback


def restore(conn: sqlite3.Connection, memory_id: str) -> dict[str, Any]:
    conn = conn
    ensure_schema(conn)
    text = text_of(conn, memory_id)
    if not text:
        return {"ok": False, "error": "cold copy not found"}
    now = _now()
    conn.execute(
        "UPDATE memories SET text=?, status='active', archived_at=NULL, updated_at=? WHERE id=?",
        (text, now, str(memory_id)),
    )
    conn.execute("DELETE FROM mem_cold WHERE memory_id=?", (str(memory_id),))
    conn.commit()
    return {"ok": True, "memory_id": str(memory_id), "chars": len(text)}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "soulcore.db"))
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--restore", default="")
    args = ap.parse_args()
    target = os.environ.get("EMOTIONCORE_DB") or args.db
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    try:
        if args.restore:
            print(json.dumps(restore(conn, args.restore), ensure_ascii=False))
        elif args.run:
            print(json.dumps(run(conn, limit=args.limit or 200), ensure_ascii=False, indent=2))
        else:
            out = plan(conn, limit=args.limit)
            out.pop("cfg", None)
            print(json.dumps(out, ensure_ascii=False, indent=2))
    finally:
        conn.close()
