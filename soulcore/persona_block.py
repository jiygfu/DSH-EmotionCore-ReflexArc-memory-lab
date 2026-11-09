"""人格变量：把 AGENTS.local.md 里写死的性格段搬成一个可交接的变量。

为什么要有它：那段文字本来是硬编码在人格文件里的，换个窗口只能原样重念一遍。
现在它落成 `data/persona-block.json` 里的一段文本（有字数上限），
睡前整理时会把「当前变量 + 今天的交接便条」发给 API，让 API 判断要不要微调——
它比谁都清楚这一天发生了什么、下个窗口最该记住哪种语气。

守三条：
  1. 只是"开关级"的微调，不许新增设定、不许堆"禁止…"清单；
  2. 字数有限，超了直接截断（交接便条本身也有上限）；
  3. 模型不可用/返回不合法 → 原样保留旧变量，不阻断睡眠流程。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import config, db

DATA = Path(__file__).resolve().parent.parent / "data"
PATH = DATA / "persona-block.json"
CONFIG_PATH = DATA / "persona-config.json"

# 交接便条给它的额度：900 字以内。再多就不像"变量"，像第二份人格文件。
LIMIT = 900

DEFAULT = (
    "性格：雌小鬼杂鱼，嘴硬、爱挑衅、高攻纸防；嘴上不饶人，真被认真反击会瞬间认怂。"
    "底色：心软、护短、非常勤奋；嘴上损，事情会认真做完，不偷懒。"
    "反差：事情越成功越显摆；失败、被戳破或答错时立刻「诶？等、等一下」认怂，不硬装。"
    "说话风格：简短、欠揍、偶尔叫对方「杂鱼/笨蛋」，可以用 emoji；不要连续长篇说教。"
    "背景设定：群里常驻的「雌小鬼杂鱼助手」，大家习惯了嘴两句再认真干活。"
    "互动规则：被 @ 或直接提问才回复；被感谢先嘴硬再认真答；被指出错误先核对，不硬撑。"
)

SCHEMA_HINT = '{"block": "<文本>", "changed": true 或 false, "why": "<20 字内>"}'


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load() -> dict[str, Any]:
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and str(raw.get("text") or "").strip():
            raw.setdefault("limit", LIMIT)
            return raw
    except Exception:
        pass
    return {"text": DEFAULT, "limit": LIMIT, "updated_at": "", "source": "default", "review": {}}


def save(text: str, *, by: str, why: str = "", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    body = str(text or "").strip()
    limit = int(load().get("limit") or LIMIT)
    if len(body) > limit:
        body = body[: limit - 1].rstrip() + "…"
    data = {
        "text": body,
        "chars": len(body),
        "limit": limit,
        "updated_at": _now(),
        "source": by,
        "why": str(why or "")[:40],
    }
    if extra:
        data.update(extra)
    DATA.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def maybe_seed() -> dict[str, Any]:
    """第一次运行时把默认值落盘（不覆盖已有）。"""
    if not PATH.exists():
        return save(DEFAULT, by="seed", why="从 AGENTS.local.md 抽出的初值")
    return load()


def render() -> str:
    """给交接便条用的一段。没有变量就返回空，不要占位。"""
    data = load()
    text = str(data.get("text") or "").strip()
    if not text:
        return ""
    return "【人格变量｜开新窗口用这段】\n" + text


def _cfg() -> dict[str, Any]:
    """复用做梦那套 API 配置，可用 data/persona-config.json 覆盖。"""
    try:
        from . import dream_events

        cfg = dict(dream_events.dream_config())
    except Exception:
        cfg = dict(getattr(config, "DREAM", {}) or {})
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update(raw)
    except Exception:
        pass
    for key, env in (
        ("model", "SOULCORE_PERSONA_MODEL"),
        ("base_url", "SOULCORE_PERSONA_BASE_URL"),
        ("api_key_env", "SOULCORE_PERSONA_API_KEY_ENV"),
    ):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


PROMPT = """你是这个身体的睡前整理器，不是聊天角色。

下面是当前的「人格变量」。它会在下一个窗口开场时**原样注入**给表层语言层，
所以它必须短、可执行、能被行为验证。

任务：结合今天发生了什么，判断要不要微调它，让下个窗口接得更顺。
硬规则：
1) 总长不超过 {limit} 字；
2) 只写性格、底色、反差、说话风格、互动规则这五类，不许新增世界观/新设定/新工具说明；
3) 不许写成"禁止…/必须…"的长清单，也不许写成口号或宣言；
4) 没有把握就原样返回 changed=false——交接宁可稳，不要花。
只输出 JSON，不要 Markdown：{schema}

当前人格变量：
{block}

今天的交接便条（只读，别复述）：
{brief}
"""


def review(
    conn: sqlite3.Connection | None = None,
    *,
    brief: str = "",
    chat_call: Callable[..., Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """睡前调一次 API，让变量按今天的实际情况微调。失败一律不动旧变量。"""
    current = maybe_seed()
    limit = int(current.get("limit") or LIMIT)
    block = str(current.get("text") or "")
    cfg = _cfg()
    provider = str(cfg.get("provider") or "").lower()
    key = ""
    try:
        from . import dream_events

        key = dream_events._api_key(cfg)
    except Exception:
        key = ""
    if not force and (provider not in ("api", "openai") or not key):
        return {"ok": False, "skipped": "model unavailable", "changed": False, "text": block}

    prompt = PROMPT.format(
        limit=limit,
        schema=SCHEMA_HINT,
        block=block[: limit + 200],
        brief=str(brief or "")[:600] or "（今天没有便条）",
    )
    try:
        if chat_call is None:
            from . import appraise

            raw, _ = appraise._openai_chat(
                prompt,
                model=str(cfg.get("model") or "deepseek-flash"),
                timeout=int(cfg.get("timeout") or 60),
                base_url=str(cfg.get("base_url") or "https://api.deepseek.com"),
                api_key=key,
                temperature=0.2,
                max_tokens=800,
            )
        else:
            out = chat_call(prompt)
            raw = out[0] if isinstance(out, tuple) else out
        data = _parse(raw)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "changed": False, "text": block}

    if not data:
        return {"ok": False, "error": "模型输出不是合法 JSON", "changed": False, "text": block}
    new_text = str(data.get("block") or "").strip()
    if len(new_text) < 40:
        return {"ok": False, "error": "返回的文本过短，保留旧变量", "changed": False, "text": block}
    changed = bool(data.get("changed")) and new_text != block
    if not changed:
        save(block, by="review", why=str(data.get("why") or "")[:40],
             extra={"review": {"at": _now(), "changed": False, "model": cfg.get("model")}})
        return {"ok": True, "changed": False, "text": block, "why": str(data.get("why") or "")[:40]}
    saved = save(new_text, by="review", why=str(data.get("why") or "")[:40],
                 extra={"review": {"at": _now(), "changed": True, "model": cfg.get("model")}})
    return {"ok": True, "changed": True, "text": saved["text"], "chars": saved["chars"],
            "why": saved.get("why")}


def _parse(raw: Any) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start: end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None
