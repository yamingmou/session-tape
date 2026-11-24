"""目标：pi（`@mariozechner/pi-coding-agent`）。

格式依据是它自己的 `docs/session-format.md`（不是猜）：
  header  `{"type":"session","version":3,"id":<uuid>,"timestamp":ISO,"cwd":...}`
  entry   `{"type":"message","id":<8位hex>,"parentId":<上一条id|null>,"timestamp":ISO,
            "message":{...}}`
  条目 id 是 **8 位十六进制**，靠 `parentId` 串成一棵树（线性时就是一条链）。

必须自己做对的两件事：
  ① **id 链重造**：不能搬源的 id（源是 uuid / 数字 id，pi 认 8 位 hex）；
  ② assistant 要带 `provider`/`model`/`usage`/`stopReason` —— 这些是 pi 的必填外壳。
     用占位值即可（实测占位 `model` 不影响它读、也不影响续跑），但**不能留空**。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc) \
                   .isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _zero_usage() -> dict:
    return {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}


def render(msgs, cwd: str, *, title: str = "", model: str = "migrated") -> str:
    """渲染成 pi 的 jsonl 文本（一行一个 JSON），末尾带换行。"""
    if not msgs:
        raise SystemExit("✗ 没有可搬的消息（源里全是占位/工具内容？）")

    # 时间戳补齐：源里缺的按上一条 +1s 递推，保证单调；
    # 整段都没有时间（读源时全 0）⇒ 退回"现在"，否则会落到 1970（实测踩过）。
    stamps: list[int] = []
    prev = int(msgs[0].ts_ms or 0) or int(datetime.now().timestamp() * 1000)
    for m in msgs:
        ts = m.ts_ms or (prev + 1000 if prev else 0)
        if ts <= prev:
            ts = prev + 1000
        stamps.append(ts)
        prev = ts

    header = {
        "type": "session", "version": 3,
        "id": str(uuid.uuid4()),
        "timestamp": _iso(stamps[0]),
        "cwd": cwd,
    }
    lines = [json.dumps(header, ensure_ascii=False)]

    parent = None
    for i, (m, ts) in enumerate(zip(msgs, stamps), 1):
        eid = f"{i:08x}"
        payload = {"timestamp": ts}
        if m.role == "user":
            payload.update({"role": "user", "content": m.text})
        else:
            payload.update({
                "role": "assistant",
                "content": [{"type": "text", "text": m.text}],
                "api": "openai-completions", "provider": "migrated", "model": model,
                "usage": _zero_usage(), "stopReason": "stop",
            })
        lines.append(json.dumps({"type": "message", "id": eid, "parentId": parent,
                                 "timestamp": _iso(ts), "message": payload},
                                ensure_ascii=False))
        parent = eid

    return "\n".join(lines) + "\n"
