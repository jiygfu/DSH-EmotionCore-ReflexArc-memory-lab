#!/usr/bin/env python3
"""Read-only Phase-1 shadow: local session chunks + event-worthy gate.

No database writes, no API calls. It is a design probe for the future
"session chunk -> event stream" pipeline:
  - group a day by conversation_key + time gap;
  - mark micro chat that should not become a long-term event;
  - mark normal/major chunks;
  - make a local extractive summary.

Usage:
  python scripts/event_stream_shadow.py --day 2026-11-03
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "soulcore.db"
DEFAULT_OUT = ROOT / "reports"

COMMIT_RE = re.compile(r"(答应|约好|说好|一定|必须|截止|deadline|明天|下次|回头|记得|别忘|等你|还没|没做完|继续)")
KNOW_RE = re.compile(r"(为什么|怎么|如何|原理|代码|报错|模型|学习|教程|论文|算法|查一下|搜一下|解释|区别|什么意思|能不能|是不是|有没有)")
LONG_RE = re.compile(r"(长期|以后|持续|一直|以后都|计划|目标|习惯|需要)")
EMO_RE = re.compile(r"(喜欢|讨厌|生气|难过|开心|担心|害怕|对不起|道歉|烦)")
CONFLICT_RE = re.compile(r"(吵|冲突|生气|对不起|道歉|敏感)")
ROLEPLAY_RE = re.compile(r"(跑团|扮演|剧情|回合|检定|骰|dm|npc|夜场|旁白|你走进|门楣|金铃|角色卡|主持人)")
STAGE_RE = re.compile(r"[（(][^）)]{2,}[）)]")
TECH_RE = re.compile(r"(模型|代码|api|配置|部署|上下文|数据库|接口|测试|报错|本地|系统|程序|token|记忆|检索|提示词)")


def parse_ts(value: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.astimezone()
    except Exception:
        return None


def clean(text: str | None, limit: int = 500) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def signals(text: str) -> list[str]:
    out = []
    for name, rx in (
        ("commitment", COMMIT_RE),
        ("knowledge", KNOW_RE),
        ("long_term", LONG_RE),
        ("emotion", EMO_RE),
        ("conflict", CONFLICT_RE),
    ):
        if rx.search(text or ""):
            out.append(name)
    return out


def classify(items: list[sqlite3.Row], duration_min: float) -> tuple[str, list[str], str, str, bool]:
    text = " ".join(str(x["text"] or "") for x in items)
    sig = signals(text)
    max_imp = max(float(x["importance"] or 0) for x in items)
    max_unres = max(float(x["unresolved"] or 0) for x in items)
    rp_terms = set(ROLEPLAY_RE.findall(text.lower()))
    rp_score = len(rp_terms) + (1 if STAGE_RE.search(text) and len(rp_terms) >= 2 else 0)
    tech_score = len(set(TECH_RE.findall(text.lower())))
    if rp_score >= 3 and tech_score < 3:
        # Roleplay/scenario commitments are in-fiction. Never promote them into
        # long-term personality promises; keep a normal entertainment archive.
        kind = "micro" if len(items) <= 2 and duration_min <= 10 else "normal"
        return kind, sig, "roleplay/entertainment", "roleplay_entertainment", False
    if "commitment" in sig or "knowledge" in sig or "long_term" in sig or "conflict" in sig:
        return "major", sig, "strong signal", "ordinary", True
    if max_imp >= 0.55 or max_unres >= 0.50:
        return "major", sig, "high importance/unresolved", "ordinary", True
    if len(items) <= 2 and duration_min <= 10 and not sig:
        return "micro", sig, "short chat", "ordinary", False
    return "normal", sig, "ordinary multi-turn", "ordinary", False


def extractive_summary(items: list[sqlite3.Row]) -> str:
    if not items:
        return ""
    best = max(items, key=lambda x: float(x["importance"] or 0))
    bits = [clean(items[0]["text"], 90)]
    if best["id"] != items[0]["id"]:
        bits.append(clean(best["text"], 90))
    if items[-1]["id"] not in (items[0]["id"], best["id"]):
        bits.append(clean(items[-1]["text"], 90))
    summary = "；".join(dict.fromkeys(x for x in bits if x))
    if len(items) > 2:
        summary += f"（共 {len(items)} 条）"
    return summary[:300]


def load(conn: sqlite3.Connection, day: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT m.id,m.text,m.ts,m.speaker,m.person_id,m.conversation_key,
                  m.importance,
                  a.unresolved, a.dimensions_json, a.felt
           FROM memories m
           LEFT JOIN appraisals a ON a.id = (
             SELECT id FROM appraisals WHERE memory_id=m.id ORDER BY id DESC LIMIT 1
           )
           WHERE substr(COALESCE(m.ts,m.created_at),1,10)=?
             AND m.status='active' AND COALESCE(m.sensitive,0)=0
           ORDER BY COALESCE(m.ts,m.created_at) ASC""",
        (day,),
    ).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--day", default=datetime.now().astimezone().date().isoformat())
    ap.add_argument("--gap-min", type=float, default=20)
    ap.add_argument("--max-items", type=int, default=20)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    conn = sqlite3.connect("file:" + str(Path(args.db)) + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = load(conn, args.day)
    conn.close()

    chunks = []
    current: list[sqlite3.Row] = []
    last: datetime | None = None
    last_conv = ""
    for row in rows:
        dt = parse_ts(row["ts"])
        if dt is None:
            continue
        conv = str(row["conversation_key"] or "")
        if current and (conv != last_conv or (last and (dt - last) > timedelta(minutes=args.gap_min))
                        or len(current) >= args.max_items):
            chunks.append(current)
            current = []
        current.append(row)
        last, last_conv = dt, conv
    if current:
        chunks.append(current)

    out = []
    for i, items in enumerate(chunks, 1):
        start = parse_ts(items[0]["ts"])
        end = parse_ts(items[-1]["ts"])
        duration = ((end - start).total_seconds() / 60) if start and end else 0
        kind, sig, reason, content_class, long_term_eligible = classify(items, duration)
        participants = sorted({str(x["speaker"] or "") for x in items if x["speaker"]})
        out.append({
            "chunk_id": f"shadow_chunk_{args.day}_{i:03d}",
            "day": args.day,
            "conversation_key": items[0]["conversation_key"],
            "start": items[0]["ts"],
            "end": items[-1]["ts"],
            "duration_min": round(duration, 1),
            "items": len(items),
            "participants": participants,
            "event_class": kind,
            "content_class": content_class,
            "domain": "roleplay" if content_class == "roleplay_entertainment" else "real",
            "long_term_eligible": long_term_eligible,
            "personality_eligible": bool(long_term_eligible and content_class != "roleplay_entertainment"),
            "confidence_tier": "low" if content_class == "roleplay_entertainment" else ("medium" if kind == "major" else "low"),
            "reference_weight": 0.60 if content_class == "roleplay_entertainment" else (1.0 if kind == "major" else (0.30 if kind == "micro" else 0.75)),
            "emotion_boost": ["fun", "curiosity"] if content_class == "roleplay_entertainment" else [],
            "signals": sig,
            "signal_scope": "fiction" if content_class == "roleplay_entertainment" else "real",
            "reason": reason,
            "summary": extractive_summary(items),
            "memory_ids": [x["id"] for x in items],
            "max_unresolved": round(max(float(x["unresolved"] or 0) for x in items), 3),
            "max_importance": round(max(float(x["importance"] or 0) for x in items), 3),
        })

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"event-stream-shadow-{args.day}.json"
    md_path = out_dir / f"event-stream-shadow-{args.day}.md"
    payload = {
        "day": args.day,
        "generated_at": datetime.now().astimezone().isoformat(),
        "gap_min": args.gap_min,
        "max_items": args.max_items,
        "chunks": out,
        "stats": dict(Counter(x["event_class"] for x in out)),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 事件流 shadow：{args.day}",
        "",
        f"- chunks：{len(out)}",
        f"- 分类：{json.dumps(payload['stats'], ensure_ascii=False)}",
        f"- 原始消息：{len(rows)}",
        "",
        "> 只读 shadow；没有写数据库，没有调用 API。",
        "",
        "| chunk | 时间 | 会话 | 条数 | 分类 | 内容类型 | 域 | 置信 | 参考权重 | 长期资格 | 信号 | 摘要 |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for x in out:
        conv = "私聊" if str(x["conversation_key"]).startswith("private:") else ("群聊" if str(x["conversation_key"]).startswith("group:") else "未知")
        lines.append(
            f"| {x['chunk_id']} | {clean(x['start'],19)} → {clean(x['end'],19)} | {conv} | {x['items']} | {x['event_class']} | {x['content_class']} | {x['domain']} | {x['confidence_tier']} | {x['reference_weight']:.2f} | {'是' if x['long_term_eligible'] else '否'} | {','.join(x['signals']) or '-'} | {clean(x['summary'],70)} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "json": str(json_path), "md": str(md_path),
        "day": args.day, "chunks": len(out), "stats": payload["stats"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
