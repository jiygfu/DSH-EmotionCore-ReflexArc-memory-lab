"""Sleep-time maintenance of open loops (M4).

单写者是桥接：这里只发一个请求让它自己清，Python 不直接写 loops.jsonl。
失败一律降级为 no-op —— 睡眠流程不能因为清理失败而中断。
"""
from __future__ import annotations

import json
import urllib.request

from . import session_rotation


def maintain(timeout: float = 5.0) -> dict:
    try:
        base, token = session_rotation._bridge()
    except Exception:
        return {"ok": False, "error": "bridge not found"}
    if not base:
        return {"ok": False, "error": "bridge not found"}
    req = urllib.request.Request(
        base.rstrip("/") + "/api/loops/maintain",
        data=b"{}",
        method="POST",
        headers={
            "content-type": "application/json",
            **({"x-console-token": token} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - 睡眠流程不因清理失败中断
        return {"ok": False, "error": str(exc)}
