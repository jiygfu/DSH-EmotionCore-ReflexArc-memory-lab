"""Dream diary + next-day plan, generated locally.

This is deliberately separate from SurfCore's B站 `whale-diary.md`:
  - no SurfCore file writes;
  - local Ollama only;
  - deterministic fallback if the model is unavailable.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import appraise, db

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "diary": {"type": "string", "minLength": 1, "maxLength": 1200},
        "plan": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {"type": "string", "minLength": 1, "maxLength": 120},
        },
    },
    "required": ["diary", "plan"],
}

PROMPT = """你是桌宠的睡前整理器，不是聊天角色。请只输出 JSON，不要 Markdown。

根据下面材料，写：
1. 一段第一人称睡前日记（3~6 句），写今天真正记住/在意的，不要诊断，不要夸张。
2. 明天计划 1~3 条，要具体、轻量、可执行。

只能使用材料里能支持的事实；不确定就写“还不确定”，不要补不存在的细节。

材料：
{context}
"""


def _fallback(items: list[sqlite3.Row], p: dict[str, Any]) -> dict[str, Any]:
    today = sum(1 for r in items if r["reason"] == "today_important")
    old = sum(1 for r in items if r["reason"] == "random_untriggered")
    diary = (
        f"今天留下了 {today} 件我真正记得的事，睡前又浮起 {old} 件旧事。"
        f"现在的我，安全感大约 {p.get('security', 0):.2f}，"
        f"警惕大约 {p.get('caution', 0):.2f}，效价 {p.get('valence', 0):+.2f}。"
        "有些事还没完全想明白，但不用今晚全部想完。"
    )
    plan = ["先完成今天最在意的一件事。", "如果还有余力，再碰一件拖了很久的小事。"]
    return {"diary": diary, "plan": plan, "status": "fallback"}


def generate(
    conn: sqlite3.Connection,
    *,
    dream_id: int,
    day: str,
    p: dict[str, Any],
    model: str = db.MODEL,
    timeout: int = 180,
) -> dict[str, Any]:
    items = conn.execute(
        """SELECT m.id, m.scope, m.text, i.reason
           FROM dream_items i JOIN memories m ON m.id = i.memory_id
           WHERE i.dream_id = ?
           ORDER BY CASE i.reason WHEN 'today_important' THEN 0 ELSE 1 END, m.id
           LIMIT 12""",
        (dream_id,),
    ).fetchall()
    context_items = [
        {
            "scope": r["scope"],
            "reason": r["reason"],
            "text": (r["text"] or "")[:600],
        }
        for r in items
    ]
    context = {
        "date": day,
        "P": p,
        "memories": context_items,
    }
    body = {
        "model": model,
        "prompt": PROMPT.format(context=json.dumps(context, ensure_ascii=False)[:6000]),
        "stream": False,
        "format": SCHEMA,
        "keep_alive": "30s",
        "options": {
            "temperature": 0.5,
            "top_p": 0.9,
            "num_ctx": 3072,
            "num_predict": 420,
            "num_thread": 4,
        },
    }
    try:
        data = appraise._post_json("/api/generate", body, timeout=timeout)
        raw = str(data.get("response") or "")
        obj = json.loads(appraise._strip_json(raw))
        diary = str(obj.get("diary") or "").strip()
        plan = [str(x).strip() for x in (obj.get("plan") or []) if str(x).strip()]
        if not diary or not plan:
            raise ValueError("empty diary/plan")
        result = {"diary": diary[:1200], "plan": plan[:3], "status": "ok"}
    except Exception as exc:
        result = _fallback(items, p)
        result["error"] = str(exc)[:300]

    conn.execute(
        """UPDATE dream_runs SET diary_text=?, plan_json=?, diary_status=? WHERE id=?""",
        (result["diary"], json.dumps(result["plan"], ensure_ascii=False),
         result["status"], dream_id),
    )
    conn.commit()

    # Local, visible artifact; never inside SurfCore.
    out_dir = Path(db.ROOT) / "diary"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {day} 睡前日记",
        "",
        result["diary"],
        "",
        "## 明天",
        "",
    ]
    lines += [f"- {x}" for x in result["plan"]]
    lines += ["", "## P (shadow, not injected)", "", "```json",
              json.dumps(p, ensure_ascii=False, indent=2), "```", ""]
    (out_dir / f"{day}.md").write_text("\n".join(lines), encoding="utf-8")
    result["path"] = str(out_dir / f"{day}.md")
    return result
