"""S12-D：事件边界用「变化点」而不是单一固定时钟。

旧做法：同窗口 + 间隔 > 20 分钟 + 最多 12 条就切一刀。问题是：
- 两个人接着聊了半小时不停，会被 12 条上限硬切；
- 中间去泡了杯茶回来接着同一件事说，会被 20 分钟硬切成两段；
- 一句「晚安」之后的时间差，比任何阈值都更说明"这件事完了"。

新做法把六个信号加权成一个变化分，超过阈值才切：
间隔 / 窗口变化 / 话题漂移 / 参与者变化 / 收尾语 / 未解决度突增。

默认**不启用**（`data/recall-config.json` → `eventBoundary: "clock"`），
因为手工标注集还没做全；启用只需改成 `"change"`。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

GAP_MINUTES = 20          # 旧时钟阈值，保留作基线
HARD_GAP_MINUTES = 90     # 超过这个间隔，几乎一定是新事件
MAX_ITEMS = 12            # 旧上限，现在只作为"软"信号
THRESHOLD = 1.0           # 变化分超过它才切

ENDING_RE = re.compile(r"(晚安|拜拜|再见|886|先这样|先这么着|先撤|溜了|去忙|下了|睡了|不聊了|回头聊|改天聊|明天聊|下次聊|到此为止)")
SETTLED_RE = re.compile(r"(说好了|就这么定|扯平|一言为定|成交|定了|好啦|行啦|算啦|翻篇)")
QUESTION_TAIL = re.compile(r"([?？]\s*$|(吗|嘛|么|咋|怎么|为什么|为啥|什么|哪个|哪里|哪儿|谁|多少|几点|是不是|有没有|能不能|可不可以|要不要|好不好|对不对|行不行)\s*[。！!…～~]*$)")


def _parse(ts: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.astimezone()
        return d.astimezone()
    except Exception:
        return None


def _bigrams(text: str) -> set[str]:
    s = "".join(ch for ch in str(text or "") if not ch.isspace())
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else set()


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _context_bigrams(history: list[dict[str, Any]], k: int = 3) -> set[str]:
    """最近 k 条（含当前段更早的）合起来的词面，用来判"这句和刚才聊的还是一回事吗"。"""
    merged: set[str] = set()
    for row in history[-k:]:
        merged |= _bigrams(str(row.get("text") or ""))
    return merged


def _cos(a: Any, b: Any) -> float:
    try:
        import numpy as np

        va = np.asarray(a, dtype="float32")
        vb = np.asarray(b, dtype="float32")
        na = float(np.linalg.norm(va))
        nb = float(np.linalg.norm(vb))
        if na <= 0 or nb <= 0:
            return 0.0
        return float(va @ vb / (na * nb))
    except Exception:
        return 0.0


def _centroid(vectors: list[Any]) -> Any | None:
    if not vectors:
        return None
    try:
        import numpy as np

        return np.mean(np.stack([np.asarray(v, dtype="float32") for v in vectors]), axis=0)
    except Exception:
        return None


def change_score(
    prev: dict[str, Any],
    cur: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    *,
    vectors: dict[str, Any] | None = None,
) -> tuple[float, list[str]]:
    """两个相邻条目之间的变化分；分数越高越像"新事件开始"。

    history = 当前段已有的条目（按时间升序，含 prev）。给了它，话题判断就和
    "这段最近在聊什么"比，而不是和上一句比——一问一答本来就不共享几个词。
    """
    score = 0.0
    why: list[str] = []

    gap_min = 0.0
    t0, t1 = _parse(prev.get("ts")), _parse(cur.get("ts"))
    if t0 and t1:
        gap_min = max(0.0, (t1 - t0).total_seconds() / 60.0)
    if gap_min >= HARD_GAP_MINUTES:
        score += 1.2
        why.append(f"间隔{gap_min:.0f}min")
    elif gap_min > GAP_MINUTES:
        score += min(0.8, 0.8 * (gap_min - GAP_MINUTES) / (HARD_GAP_MINUTES - GAP_MINUTES) + 0.2)
        why.append(f"间隔{gap_min:.0f}min")

    if str(prev.get("conversation_key") or "") != str(cur.get("conversation_key") or ""):
        score += 1.0
        why.append("换窗口")

    if vectors:
        seg_vecs = [
            vectors[r["id"]] for r in (history or [prev]) if str(r.get("id")) in vectors
        ]
        cur_vec = vectors.get(str(cur.get("id")))
        centroid = _centroid(seg_vecs)
        if cur_vec is not None and centroid is not None:
            sim = _cos(cur_vec, centroid)
            if sim < 0.45:
                score += 0.9
                why.append(f"话题跳变({sim:.2f})")
            elif sim < 0.55:
                score += 0.45
                why.append(f"话题漂移({sim:.2f})")
        else:
            score -= 0.0
    else:
        ctx = _context_bigrams(history or [prev])
        drift = 1.0 - _jaccard(ctx, _bigrams(cur.get("text", "")))
        if drift >= 0.95:
            score += 0.9
            why.append("话题跳变")
        elif drift >= 0.85:
            score += 0.45
            why.append("话题漂移")

    sp_prev = str(prev.get("speaker") or "")
    sp_cur = str(cur.get("speaker") or "")
    if sp_prev and sp_cur and sp_prev != sp_cur:
        prev_is_q = bool(QUESTION_TAIL.search(str(prev.get("text") or "")))
        # 提问换人回答是"同一个事件"，不是边界；只有并非问答时才当参与者变化
        if prev_is_q:
            score -= 0.1
        else:
            score += 0.15
            why.append("换人")

    prev_text = str(prev.get("text") or "")
    if ENDING_RE.search(prev_text) and len(prev_text) <= 30:
        score += 1.0
        why.append("道别")
    elif SETTLED_RE.search(prev_text):
        score += 0.6
        why.append("收束")

    # 段长度只做"软"信号：旧版是硬切 12 条，这里让它变成"越聊越长越容易收一刀"
    n_ctx = len(history or [prev])
    # 旧版的"12 条硬切"在这里变成一个够强的软信号：到点就切，但前面若有更明确的
    # 道别/换窗口/话题跳变，会先切在那些地方，而不是死板地数到 12
    if n_ctx >= 20:
        score += 1.2
        why.append(f"段过长({n_ctx})")
    elif n_ctx >= 12:
        score += 1.0
        why.append(f"段偏长({n_ctx})")

    try:
        d_unres = abs(float(cur.get("unresolved") or 0.0) - float(prev.get("unresolved") or 0.0))
    except Exception:
        d_unres = 0.0
    if d_unres >= 0.3:
        score += 0.5
        why.append(f"未解决度跳{d_unres:.2f}")

    return round(score, 3), why


def segment(
    rows: Iterable[dict[str, Any]],
    *,
    threshold: float = THRESHOLD,
    vectors: dict[str, Any] | None = None,
) -> list[list[dict[str, Any]]]:
    """把一天的行切成事件段。rows 需按 ts 升序，含 ts/text/speaker/conversation_key/unresolved。"""
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for row in rows:
        if current:
            score, _ = change_score(current[-1], row, current, vectors=vectors)
            if score >= threshold:
                groups.append(current)
                current = []
        current.append(row)
    if current:
        groups.append(current)
    return groups


def boundaries(
    rows: list[dict[str, Any]], *, vectors: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """列出所有判定为边界的位置，带原因，方便人工标注与复核。"""
    out: list[dict[str, Any]] = []
    for i in range(1, len(rows)):
        history = rows[max(0, i - 6):i]
        score, why = change_score(rows[i - 1], rows[i], history, vectors=vectors)
        out.append({
            "index": i,
            "score": score,
            "reasons": why,
            "is_boundary": score >= THRESHOLD,
            "before": str(rows[i - 1].get("text") or "")[:40],
            "after": str(rows[i].get("text") or "")[:40],
        })
    return out
