"""B1 检查器：群记忆 Markdown（qq-memory/<群号>.md）与 soulcore 记忆库有没有记同一件事。

现在 group-memory 插件是关的（config.json 里 group-memory=false），所以这个目录不存在；
将来打开前先跑一遍这个脚本，确认 md 里写的不是"人物事实/承诺"——那些的唯一归属是 soulcore。

用法：python tools/mem-overlap.py [--min 0.55] [--show 5]
只读，不写库、不改文件。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM_DIR = Path.home() / ".dsh" / "dsh-onebot-qq" / "qq-memory"
DB = ROOT / "data" / "soulcore.db"

STOP = set("的了是我你他她它们这那有在和就都也很吗呢吧啊呀哦嗯一个不没很还")


def grams(text: str, n: int = 2) -> set[str]:
    s = re.sub(r"[\s\W_]+", "", str(text or ""))
    return {s[i:i + n] for i in range(len(s) - n + 1)} - STOP if len(s) >= n else set()


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def md_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = re.sub(r"^[\s\-*#>|]+", "", line).strip()
        if len(text) >= 8 and not text.startswith("<!--"):
            out.append(text)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=0.55, help="相似度阈值（2-gram Jaccard）")
    ap.add_argument("--show", type=int, default=5, help="每组最多打印几条")
    args = ap.parse_args()

    if not MEM_DIR.exists():
        print(f"qq-memory 目录不存在（{MEM_DIR}）：group-memory 插件现在是关的，没有重复风险。")
        return 0

    files = sorted(MEM_DIR.glob("*.md"))
    if not files:
        print(f"{MEM_DIR} 里没有 md 文件。")
        return 0

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT id, text, conversation_key FROM memories WHERE COALESCE(sensitive,0)=0 AND status='active'"
    )]
    conn.close()

    total = 0
    for path in files:
        hits = []
        for line in md_lines(path):
            g = grams(line)
            if not g:
                continue
            best, best_score = None, 0.0
            for row in rows:
                score = jaccard(g, grams(str(row.get("text") or "")[:400]))
                if score > best_score:
                    best, best_score = row, score
            if best_score >= args.min:
                hits.append((best_score, line, best))
        total += len(hits)
        print(f"\n== {path.name}：{len(hits)} 条与记忆库高度重合 ==")
        for score, line, row in sorted(hits, key=lambda x: -x[0])[: args.show]:
            print(f"  {score:.2f}  md『{line[:50]}』")
            print(f"        db[{row['id']}] 『{str(row['text'])[:50]}』")

    print(f"\n合计 {total} 条重合。结论：")
    if total == 0:
        print("  两层没有记同一件事，可以继续用。")
    else:
        print("  上面这些应该只留在 soulcore；md 里只该放「群内梗/口头禅/气氛」，不放人物事实与承诺。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
