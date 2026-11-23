"""目标：OpenClaw。

**为什么这个文件这么薄**：OpenClaw 的转录与 pi **同形**——同一个 header v3
（`{"type":"session","version":3,"id","timestamp","cwd"}`）+ 同样的 `message` 条目
（8 位 hex `id` + `parentId` 链 + `message.role` / `message.content[]`）。
依据是上游文档里的行样例（`reference/agent-session-sync/agents/openclaw.md` 第 46–56 行），
不是我们猜的；它的读取判断依据也继承自同一套基类。

差别只在**存放位置与后端**：
  · 旧版（≤2026.7.1）：`~/.openclaw/agents/<agent>/sessions/` 下的 jsonl；
  · 新版（≥2026.7.2）：正典在 `openclaw-agent.sqlite` 的 `transcript_events`（`event_json` 同形）；
  · 迁移到**新版**要走库、且需要该产品的 `sessions` 行 —— 与本机无样本，因此
    `write()` 只做"落成 jsonl"，**升级/登记留给产品的 doctor 或后续版本**。

⚠️ 本机没有装 OpenClaw，**这一家只到 L1（我方读器往返）**，没有真机验收。
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from . import pi


def render(msgs, cwd: str, *, title: str = "", session_id: str | None = None) -> list[dict]:
    """复用 pi 的渲染（同形），只把产物解析成 dict 列表返回。"""
    sid = session_id or str(uuid.uuid4())
    text = pi.render(msgs, cwd, title=title)
    lines = [json.loads(x) for x in text.strip().split("\n")]
    # 把 pi 生成的随机 session id 换成我们指定的那个（同一份内容，两处一致）
    lines[0]["id"] = sid
    # pi 的 user 正文是**字符串**，OpenClaw 按**内容块列表**解析
    # （依据：上游读器 `"".join(b["text"] for b in blocks if b["type"]=="text")`）
    # ⇒ 统一成块列表，两种读法都能吃。
    for o in lines[1:]:
        msg = o.get("message") or {}
        if isinstance(msg.get("content"), str):
            msg["content"] = [{"type": "text", "text": msg["content"]}]
    return lines


def write(lines: list[dict], out: str, session_id: str, *, agent: str = "main") -> str:
    """落到 `agents/<agent>/sessions/<sessionId>.jsonl`；`out` 是 `~/.openclaw` 这一层。"""
    base = os.path.join(os.path.expanduser(out), "agents", agent, "sessions")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{session_id}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for o in lines:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    return path
