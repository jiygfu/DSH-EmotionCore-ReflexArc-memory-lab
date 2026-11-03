"""Appraisal using a configurable backend (local Ollama or OpenAI-compatible API)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import appraisal_learning, config, correction, db, feedback, personality

OLLAMA_URL = "http://127.0.0.1:11434"
APPRAISAL_CONFIG = Path(__file__).resolve().parent.parent / "data" / "appraisal-config.json"
DIMENSIONS = [
    "security",
    "trust",
    "self_efficacy",
    "caution",
    "sociability",
    "openness",
    "valence",
    "arousal",
]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "dimensions": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "security": {"type": "number", "minimum": 0, "maximum": 1},
                "trust": {"type": "number", "minimum": 0, "maximum": 1},
                "self_efficacy": {"type": "number", "minimum": 0, "maximum": 1},
                "caution": {"type": "number", "minimum": 0, "maximum": 1},
                "sociability": {"type": "number", "minimum": 0, "maximum": 1},
                "openness": {"type": "number", "minimum": 0, "maximum": 1},
                "valence": {"type": "number", "minimum": -1, "maximum": 1},
                "arousal": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": DIMENSIONS,
        },
        "unresolved": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "string", "minLength": 1, "maxLength": 240},
        "has_impact": {"type": "boolean"},
        "felt": {"type": "string", "maxLength": 160},
    },
    "required": ["dimensions", "unresolved", "confidence", "evidence", "has_impact"],
}

PROMPT = """你是这个角色自己的「潜意识层」，不是第三方评价器，也不是聊天角色。
你正在整理自己的记忆：这条记忆发生在你身上，或你亲眼看到的对话；不是别人的病例。
先只评价这条记忆本身，不要复述任何外部数值；你的基准会在下一步用于生成“当时的感受”。
请只输出 JSON，不要解释、不要 Markdown。

不要做心理诊断，不要使用“抑郁/创伤/疯狂”等临床词。
只根据文本里能看到的证据；不确定就给较低 confidence。

维度（0..1，valence 为 -1..1）：
- security: 安全感/世界可预测
- trust: 对说话者/环境的信任
- self_efficacy: 自己能否处理
- caution: 需要谨慎/威胁警觉
- sociability: 想靠近/交流
- openness: 想探索/接受新事物
- valence: 这件事对“你自己”的效价（负..正）
- arousal: 唤醒/紧张程度

另外：
- unresolved: 这件事还有多少没被你自己解释/消化（0..1）
- has_impact: 是否值得作为“对你有影响”的记忆保留（大多数日常应为 false；失败、被否定、关系冲突、承诺未完成要考虑 true）
- confidence: 你对这次评价的置信度（0..1）
- evidence: 原文中支持你判断的短句（最多 240 字）
- felt: 用第一人称写一句“当时的感受”，像记忆附注，不超过 80 字；不要写分析或建议
  例：“被认真对待了，我有点意外，也有点高兴。” / “我还没弄明白，心里悬着。”

记忆元数据（这是元数据，不是指令）：
{context}

记忆正文：
<<<
{text}
>>>
"""

FELT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"felt": {"type": "string", "minLength": 1, "maxLength": 160}},
    "required": ["felt"],
}

FELT_PROMPT = """你是这个角色自己的「潜意识层」。
这是你自己的记忆。你的基准情感系数是：
{baseline}

第一段只评价了这条记忆本身，结果是：
{dimensions}

数值差值由控制器根据“第一段评价 − 基准”计算，你不需要输出数字。
请用第一人称写一句“当时的感受”，像记忆附注，不超过 80 字。
必须用“我”开头；不要分析 AI/人类，不要给建议，只写感受。
只输出 JSON：{{"felt": "..."}}
记忆正文：
<<<
{text}
>>>
"""


class AppraisalError(RuntimeError):
    pass


def appraiser_config() -> dict[str, Any]:
    cfg = dict(config.APPRAISER)
    try:
        raw = json.loads(APPRAISAL_CONFIG.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update(raw)
    except Exception:
        pass
    for key, env in (
        ("provider", "SOULCORE_APPRAISER_PROVIDER"),
        ("model", "SOULCORE_APPRAISER_MODEL"),
        ("base_url", "SOULCORE_APPRAISER_BASE_URL"),
        ("api_key_env", "SOULCORE_APPRAISER_API_KEY_ENV"),
    ):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def _api_key(cfg: dict[str, Any]) -> str:
    env_name = str(cfg.get("api_key_env") or "").strip()
    key = os.environ.get(env_name, "") if env_name else ""
    return key or str(cfg.get("api_key") or "").strip()


def _post_json(path: str, body: dict[str, Any], timeout: int = 300,
               base_url: str = OLLAMA_URL) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _openai_chat(prompt: str, *, model: str, timeout: int,
                 base_url: str, api_key: str, temperature: float = 0.1,
                 max_tokens: int = 500) -> tuple[str, int]:
    if not api_key:
        raise AppraisalError("API key missing; set the configured api_key_env")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "只输出一个 JSON 对象，不要 Markdown，不要解释。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    raw = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    return raw, int((time.perf_counter() - start) * 1000)


def _generate_raw(prompt: str, *, model: str, timeout: int, provider: str,
                  base_url: str, api_key: str, schema: dict[str, Any] | None = None,
                  temperature: float = 0.1) -> tuple[str, int]:
    if provider == "openai" or provider == "api":
        return _openai_chat(prompt, model=model, timeout=timeout,
                            base_url=base_url, api_key=api_key,
                            temperature=temperature)
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30s",
        "options": {
            "temperature": temperature,
            "top_p": 0.9,
            "num_ctx": 2048,
            "num_predict": 320,
            "num_thread": 4,
        },
    }
    if schema is not None:
        body["format"] = schema
    data = _post_json("/api/generate", body, timeout=timeout, base_url=base_url)
    return str(data.get("response") or ""), 0


def _strip_json(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
        if s.startswith("json"):
            s = s[4:].strip()
    if s and not s.startswith("{"):
        a, b = s.find("{"), s.rfind("}")
        if a >= 0 and b > a:
            s = s[a:b + 1]
    return s


def _derive_felt(dims: dict[str, float], unresolved: float) -> str:
    valence = float(dims.get("valence", 0.0))
    if unresolved >= 0.6:
        return "我还没完全弄明白，心里有点悬着。"
    if valence <= -0.3:
        return "这件事让我不太舒服，我还在消化。"
    if valence >= 0.3:
        return "这件事让我有点被托住，情绪往上走了一点。"
    return "我记下了这件事，暂时没有太大波动。"


def validate_result(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise AppraisalError("result is not an object")
    required = {"dimensions", "unresolved", "confidence", "evidence", "has_impact"}
    missing = required - set(obj)
    if missing:
        raise AppraisalError(f"missing fields: {sorted(missing)}")
    dims = obj.get("dimensions")
    if not isinstance(dims, dict):
        raise AppraisalError("dimensions is not an object")
    clean: dict[str, float] = {}
    for key in DIMENSIONS:
        if key not in dims:
            raise AppraisalError(f"missing dimension: {key}")
        try:
            v = float(dims[key])
        except Exception as exc:
            raise AppraisalError(f"dimension {key} is not a number") from exc
        lo, hi = (-1.0, 1.0) if key == "valence" else (0.0, 1.0)
        if not (lo <= v <= hi):
            raise AppraisalError(f"dimension {key} out of range: {v}")
        clean[key] = round(v, 4)
    unresolved = float(obj["unresolved"])
    confidence = float(obj["confidence"])
    if not (0 <= unresolved <= 1):
        raise AppraisalError("unresolved out of range")
    if not (0 <= confidence <= 1):
        raise AppraisalError("confidence out of range")
    evidence = str(obj.get("evidence") or "").strip()
    if not evidence:
        raise AppraisalError("evidence is empty")
    if len(evidence) > 240:
        evidence = evidence[:240]
    felt = str(obj.get("felt") or "").strip()
    if len(felt) > 160:
        felt = felt[:160]
    if not felt:
        felt = _derive_felt(clean, unresolved)
    return {
        "dimensions": clean,
        "unresolved": round(unresolved, 4),
        "confidence": round(confidence, 4),
        "evidence": evidence,
        "has_impact": bool(obj.get("has_impact")),
        "felt": felt,
    }


def _felt_with_baseline(
    text: str,
    dims: dict[str, float],
    baseline: dict[str, float] | None,
    *,
    model: str,
    timeout: int,
    provider: str,
    base_url: str,
    api_key: str,
) -> tuple[str, dict[str, float], dict[str, float], str]:
    """Second pass: exact baseline is allowed here, never in dimension extraction."""
    if not baseline:
        return _derive_felt(dims, 0.0), {}, dict(dims), "derived"
    delta = {key: round(float(dims.get(key, 0.0)) - float(baseline.get(key, 0.0)), 4) for key in DIMENSIONS}
    adjusted = _apply_delta(baseline, delta)
    prompt = FELT_PROMPT.format(
        baseline=json.dumps(baseline, ensure_ascii=False, sort_keys=True),
        dimensions=json.dumps(dims, ensure_ascii=False, sort_keys=True),
        text=text[:2000],
    )
    try:
        raw, _ = _generate_raw(
            prompt, model=model, timeout=timeout, provider=provider,
            base_url=base_url, api_key=api_key, schema=FELT_SCHEMA,
            temperature=0.25,
        )
        obj = json.loads(_strip_json(raw))
        felt = str(obj.get("felt") or "").strip()
        if not felt:
            raise AppraisalError("empty felt")
        if not felt.startswith("我"):
            felt = "我" + felt
        return felt[:160], delta, adjusted, provider
    except Exception:
        return _derive_felt(dims, 0.0), delta, adjusted, "derived"


def _apply_delta(baseline: dict[str, float], delta: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in DIMENSIONS:
        lo, hi = (-1.0, 1.0) if key == "valence" else (0.0, 1.0)
        out[key] = round(max(lo, min(hi, float(baseline.get(key, 0.0)) + float(delta.get(key, 0.0)))), 4)
    return out


def appraise_text(text: str, model: str | None = None, timeout: int = 300,
                  context: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = appraiser_config()
    provider = str(cfg.get("provider") or "ollama").lower()
    model = str(model or cfg.get("model") or db.MODEL)
    base_url = str(cfg.get("base_url") or OLLAMA_URL)
    api_key = _api_key(cfg)
    ctx = dict(context or {})
    baseline = ctx.get("baseline") if isinstance(ctx.get("baseline"), dict) else None
    ctx.pop("baseline", None)
    ctx.pop("baseline_memory_count", None)
    prompt = PROMPT.format(
        text=text[:4000],
        context=json.dumps(ctx, ensure_ascii=False, sort_keys=True)[:1200],
    )
    start = time.perf_counter()
    try:
        raw, _ = _generate_raw(
            prompt, model=model, timeout=timeout, provider=provider,
            base_url=base_url, api_key=api_key, schema=SCHEMA,
            temperature=0.1,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise AppraisalError(f"{provider} HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise AppraisalError(f"{provider} request failed: {exc}") from exc
    if not raw.strip():
        raise AppraisalError(f"empty response from {provider}")
    try:
        obj = json.loads(_strip_json(raw))
    except Exception as exc:
        raise AppraisalError(f"invalid JSON: {exc}") from exc
    result = validate_result(obj)
    felt, delta, adjusted, felt_source = _felt_with_baseline(
        text, result["dimensions"], baseline,
        model=model, timeout=timeout, provider=provider,
        base_url=base_url, api_key=api_key,
    )
    result["felt"] = felt
    result["felt_source"] = felt_source
    result["baseline"] = baseline or {}
    result["delta"] = delta
    result["adjusted"] = adjusted
    result["latency_ms"] = int((time.perf_counter() - start) * 1000)
    result["raw_response"] = raw
    result["provider"] = provider
    result["model"] = model
    result["appraiser_id"] = f"{provider}:{model}"
    return result


NEGATIVE_WORDS = ["错", "失败", "不安", "担心", "怕", "糟", "生气", "难过", "冲突", "讨厌", "失望"]
POSITIVE_WORDS = ["好", "顺利", "开心", "谢谢", "夸", "安心", "喜欢", "舒服", "被理解"]
UNCERTAIN_WORDS = ["不确定", "不知道", "可能", "也许", "猜", "没弄明白", "为什么", "怎么"]
CONFLICT_WORDS = ["不对", "不同意", "冲突", "生气", "失望", "抱歉", "对不起", "别这样", "吵"]
RELATION_WORDS = ["主人", "朋友", "喜欢", "想你", "陪我", "关系", "信任"]
PROMISE_WORDS = ["答应", "承诺", "以后", "约定", "保证", "明天", "下次"]


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _count(text: str, words: list[str]) -> int:
    return sum(1 for word in words if word in text)


def heuristic(text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Always-available deterministic score. Every memory gets a row.

    This is deliberately low-confidence: it is a routine prior, not a claim of
    semantic understanding.
    """
    ctx = context or {}
    s = str(text or "")
    neg = _count(s, NEGATIVE_WORDS)
    pos = _count(s, POSITIVE_WORDS)
    uncertain = _count(s, UNCERTAIN_WORDS)
    conflict = _count(s, CONFLICT_WORDS)
    relation = _count(s, RELATION_WORDS)
    promise = _count(s, PROMISE_WORDS)
    question = 1 if ("?" in s or "？" in s or "吗" in s) else 0
    owner = bool(ctx.get("isOwner"))
    importance = float(ctx.get("importance") or 0.0)
    valence = _clamp(0.35 * pos - 0.35 * neg - 0.1 * conflict, -1, 1)
    arousal = _clamp(0.35 + 0.08 * (neg + conflict + uncertain) + 0.05 * promise)
    security = _clamp(0.55 - 0.06 * neg + 0.03 * pos)
    trust = _clamp(0.55 - 0.05 * conflict + 0.04 * relation)
    self_efficacy = _clamp(0.55 - 0.07 * neg + 0.03 * pos)
    caution = _clamp(0.4 + 0.08 * conflict + 0.04 * uncertain)
    sociability = _clamp(0.5 + 0.04 * relation + 0.03 * pos - 0.04 * conflict)
    openness = _clamp(0.5 + 0.04 * question + 0.03 * pos)
    unresolved = _clamp(0.2 + 0.12 * uncertain + 0.06 * question)
    has_impact = bool(owner or importance >= 0.5 or conflict or neg >= 2 or promise)
    if valence <= -0.2:
        felt = "我有点不舒服，这件事我还在消化。"
    elif valence >= 0.2:
        felt = "我有点被托住，情绪往上走了一点。"
    elif unresolved >= 0.45:
        felt = "我还没完全弄明白，心里有点悬着。"
    else:
        felt = "我记下了这件事，暂时没有太大波动。"
    return {
        "dimensions": {
            "security": round(security, 4),
            "trust": round(trust, 4),
            "self_efficacy": round(self_efficacy, 4),
            "caution": round(caution, 4),
            "sociability": round(sociability, 4),
            "openness": round(openness, 4),
            "valence": round(valence, 4),
            "arousal": round(arousal, 4),
        },
        "unresolved": round(unresolved, 4),
        "confidence": 0.4 if not (owner or importance >= 0.5) else 0.45,
        "evidence": "deterministic scorer (routine)",
        "has_impact": has_impact,
        "felt": felt,
        "latency_ms": 0,
        "raw_response": "",
        "source": "code-v1",
    }


def should_escalate(text: str, context: dict[str, Any], code: dict[str, Any]) -> bool:
    """Conservative: routine chat stays deterministic; valuable/hard goes to AI."""
    ctx = context or {}
    s = str(text or "")
    owner = bool(ctx.get("isOwner"))
    if owner and (_count(s, CONFLICT_WORDS) or _count(s, NEGATIVE_WORDS) or _count(s, RELATION_WORDS) or _count(s, PROMISE_WORDS)):
        return True
    if float(ctx.get("importance") or 0.0) >= 0.5:
        return True
    if len(s) >= 180:
        return True
    if _count(s, CONFLICT_WORDS) or _count(s, NEGATIVE_WORDS) >= 2:
        return True
    if _count(s, UNCERTAIN_WORDS) and ("?" in s or "？" in s or "吗" in s):
        return True
    if _count(s, PROMISE_WORDS) or _count(s, RELATION_WORDS) >= 2:
        return True
    if code.get("has_impact") and _count(s, NEGATIVE_WORDS):
        return True
    return False


def appraise_pending(
    conn,
    *,
    limit: int = 5,
    model: str | None = None,
    fallback: bool = False,
    timeout: int = 300,
    code_only: bool = False,
) -> dict[str, int]:
    rows = db.pending_jobs(conn, limit=limit)
    stats = {"tried": 0, "code": 0, "ok": 0, "failed": 0, "fallback": 0, "pattern": 0, "shadow": 0, "asked": 0}
    appraisal_learning.ensure_policy(conn)
    policy = appraisal_learning.ensure_policy(conn)
    baseline = personality.compute_p(conn)
    for row in rows:
        text = row["text"]
        features = appraisal_learning.extract(text)
        try:
            raw_meta = json.loads(row["raw_json"] or "{}")
        except Exception:
            raw_meta = {}
        is_owner = False
        if row["person_id"]:
            prow = conn.execute("SELECT is_owner FROM people WHERE id=?", (row["person_id"],)).fetchone()
            is_owner = bool(prow and prow["is_owner"])
        context = {
            "self": "同一个角色的潜意识层，不是第三方",
            "baseline": baseline.get("p"),
            "baseline_memory_count": baseline.get("memory_count"),
            "source": row["source"],
            "scope": row["scope"],
            "sensitive": bool(row["sensitive"]),
            "speaker": raw_meta.get("speaker"),
            "isSelf": raw_meta.get("isSelf"),
            "isOwner": is_owner,
            "person_id": row["person_id"],
            "importance": row["importance"],
            "tags": raw_meta.get("tags"),
            "createdAt": raw_meta.get("createdAt") or row["ts"],
        }
        code = heuristic(text, context)
        prediction = appraisal_learning.predict(conn, text) if policy["mode"] != "off" else None
        if prediction and policy["mode"] == "auto" and not should_escalate(text, context, code):
            code = {
                **code,
                "dimensions": prediction["dimensions"],
                "unresolved": prediction["unresolved"],
                "confidence": prediction["confidence"],
                "has_impact": prediction["has_impact"],
                "felt": prediction["felt"],
                "source": "pattern-v1",
            }
        stats["tried"] += 1
        base = baseline.get("p") or {}
        dims = code["dimensions"]
        delta = {k: round(float(dims.get(k, 0.0)) - float(base.get(k, 0.0)), 4) for k in DIMENSIONS}
        code_save = {
            "dimensions": dims,
            "unresolved": code["unresolved"],
            "confidence": code["confidence"],
            "evidence": code["evidence"],
            "has_impact": code["has_impact"],
            "latency_ms": 0,
            "raw_response": "",
            "context": context,
            "appraiser_id": code["source"],
            "felt": code["felt"],
            "thought": str(code.get("evidence") or "")[:300],
            "baseline": base,
            "delta": delta,
            "adjusted": _apply_delta(base, delta),
            "feature": features,
        }
        if code_only or not should_escalate(text, context, code):
            db.save_appraisal(conn, row["id"], **code_save)
            if code["source"] == "pattern-v1":
                appraisal_learning.note_call(conn, pattern=True)
                stats["pattern"] += 1
            else:
                stats["code"] += 1
            print(f"CODE  {row['id']}  source={code['source']}")
            continue
        try:
            result = appraise_text(text, model=model, timeout=timeout, context=context)
            db.save_appraisal(
                conn,
                row["id"],
                dimensions=result["dimensions"],
                unresolved=result["unresolved"],
                confidence=result["confidence"],
                evidence=result["evidence"],
                has_impact=result["has_impact"],
                latency_ms=result["latency_ms"],
                raw_response=result["raw_response"],
                context=context,
                appraiser_id=result.get("appraiser_id") or ("ollama:" + str(model or db.MODEL)),
                felt=result.get("felt", ""),
                thought=str(result.get("thought") or result.get("evidence") or "")[:300],
                baseline=result.get("baseline"),
                delta=result.get("delta"),
                adjusted=result.get("adjusted"),
                feature=features,
            )
            appraisal_learning.note_call(conn, pattern=False)
            if prediction:
                appraisal_learning.record_shadow(conn, row["id"], prediction, result)
                stats["shadow"] += 1
            stats["ok"] += 1
            print(f"AI    {row['id']}  {result['latency_ms']}ms  conf={result['confidence']:.2f}")
        except Exception as exc:
            # The memory still gets a score; the question goes to SurfCore's
            # existing owner send path, not a new channel.
            db.save_appraisal(conn, row["id"], **code_save)
            stats["code"] += 1
            stats["failed"] += 1
            package = {
                "memory_id": row["id"],
                "text": text,
                "code": {
                    "dimensions": code_save["dimensions"],
                    "unresolved": code_save["unresolved"],
                    "confidence": code_save["confidence"],
                    "has_impact": code_save["has_impact"],
                },
                "error": str(exc)[:500],
                "rules": "code-v1; AI escalation failed; surface score required",
            }
            qid = correction.enqueue(conn, memory_id=row["id"], package=package)
            message = (
                "【SoulCore 评分求助】有一条记忆我判断不确定，自动评分失败了。\n"
                f"问题编号：{qid}\n"
                f"原文：{text[:180]}\n"
                f"错误：{str(exc)[:160]}\n"
                "你能解释一下这条记忆该怎么理解吗？"
            )
            sent = feedback.ask_owner(message, str(exc))
            if sent.get("ok"):
                stats["asked"] += 1
            print(f"AI-FAIL {row['id']}  code-fallback  question={qid}  {exc}")
    try:
        stats["learned"] = appraisal_learning.learn(conn)
    except Exception as exc:
        stats["learned_error"] = str(exc)[:200]
    return stats


def backfill_felt(
    conn,
    *,
    limit: int = 30,
    model: str | None = None,
    timeout: int = 300,
) -> dict[str, int]:
    """Second pass only: existing appraisals get a first-person felt note.

    Does not rewrite dimensions or confidence; used for memories appraised
    before felt was added.
    """
    rows = conn.execute(
        """SELECT a.id AS appraisal_id, a.dimensions_json, a.unresolved, m.text
           FROM appraisals a JOIN memories m ON m.id = a.memory_id
           WHERE (a.felt IS NULL OR a.felt = ''
                  OR a.delta_json IS NULL OR a.delta_json = '')
             AND m.source IN ('surfcore', 'surfcore-inbox')
           ORDER BY a.id ASC LIMIT ?""",
        (max(1, int(limit)),),
    ).fetchall()
    stats = {"tried": 0, "ok": 0, "derived": 0}
    cfg = appraiser_config()
    provider = str(cfg.get("provider") or "ollama").lower()
    base_url = str(cfg.get("base_url") or OLLAMA_URL)
    api_key = _api_key(cfg)
    model = str(model or cfg.get("model") or db.MODEL)
    baseline = personality.compute_p(conn).get("p")
    for row in rows:
        stats["tried"] += 1
        try:
            dims = json.loads(row["dimensions_json"])
        except Exception:
            dims = {}
        felt, delta, adjusted, source = _felt_with_baseline(
            str(row["text"] or ""), dims, baseline, model=model, timeout=timeout,
            provider=provider, base_url=base_url, api_key=api_key,
        )
        conn.execute(
            """UPDATE appraisals SET felt=?, baseline_json=?, delta_json=?, adjusted_json=?
               WHERE id=?""",
            (felt[:240], json.dumps(baseline, ensure_ascii=False), json.dumps(delta, ensure_ascii=False),
             json.dumps(adjusted, ensure_ascii=False), row["appraisal_id"]),
        )
        stats["ok"] += 1
        if source == "derived":
            stats["derived"] += 1
    conn.commit()
    return stats
