"""确定性隐私闸门：注入提示词之前，把不该让模型看见的字段挡掉。

设计约束（来自计划书 §5 S2）：

* **不按 scope 屏蔽**——私聊的事在群里也能被索引到，这是刻意的（跨窗一致）。
* 只做确定性正则：不调模型、不猜语义，命中就是命中。
* 群聊更严（直接丢整条），私聊只把敏感片段打码。
* 阈值/开关放在 `data/recall-config.json`，改完下一轮请求就生效，不用重启。

这里刻意不碰 `memories.sensitive` 列（那是入库时的判定），
本模块只负责"出库到提示词"这一道。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "data" / "recall-config.json"

DEFAULTS: dict[str, Any] = {
    "minSimilarity": 0.18,        # 私聊：低于此相似度不注入
    "groupMinSimilarity": 0.28,   # 群聊：更严
    "privacyGate": True,          # 总开关
    "groupDropOnHit": True,       # 群里命中敏感 → 整条丢弃（false 则只打码）
    "maxItems": 2,                # L5 注入上限（计划书 §4.2：≤3，取 2 更稳）
}

# 命中即视为敏感。顺序无关，但密码/验证码优先。
# 值部分刻意收紧到「像标识符」的程度，避免把"这个账号我忘了"这种普通话误判。
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("password", re.compile(r"(密码|口令|passw(?:or)?d|pwd)(?!学|箱|锁|本|库|安全|管理|强度|规则)\s*(?:是|为|:|：|=)?\s*\S{3,24}", re.I)),
    ("code", re.compile(r"(验证码|校验码|动态码|短信码|otp)\D{0,8}\d{3,8}", re.I)),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("idcard", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("bank", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    ("account", re.compile(r"(账号|帐号|账户|用户名|account|user(?:name)?)\s*(?:是|为|:|：|=)?\s*[A-Za-z][A-Za-z0-9._@+-]{3,}", re.I)),
    ("address", re.compile(r"(住在|地址|收货地址|家庭住址)[^，。,.！!？?\s]{0,14}?(区|路|街|号|栋|楼|室|弄|巷)")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
]

MASK = "「已隐去」"
STRICT_PLACEHOLDER = "[联想·含敏感信息，已隐去]"


def load() -> dict[str, Any]:
    """读配置；文件不存在或用坏了都回落默认值（绝不因为配置坏了挡路）。"""
    cfg = dict(DEFAULTS)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for key in DEFAULTS:
                if key in raw:
                    cfg[key] = raw[key]
    except Exception:
        pass
    return cfg


def hits(text: str) -> list[str]:
    """返回命中的类别名（去重、保序）。"""
    found: list[str] = []
    source = str(text or "")
    if not source:
        return found
    for name, pattern in PATTERNS:
        try:
            if pattern.search(source) and name not in found:
                found.append(name)
        except Exception:
            continue
    return found


def mask(text: str) -> str:
    """把敏感片段替换成占位符，保留句子其余部分。"""
    out = str(text or "")
    for _name, pattern in PATTERNS:
        try:
            out = pattern.sub(MASK, out)
        except Exception:
            continue
    return out


def gate(text: str, *, strict: bool = False) -> tuple[str, list[str]]:
    """过闸门。

    返回 ``(可用文本, 命中类别)``：
      * 不敏感 → 原文、空列表
      * 敏感 + strict（群聊）→ 空字符串（调用方据此丢弃整条）
      * 敏感 + 非 strict（私聊）→ 打码后的文本
    """
    source = str(text or "").strip()
    if not source:
        return "", []
    found = hits(source)
    if not found:
        return source, []
    if strict:
        return "", found
    return mask(source), found
