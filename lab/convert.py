#!/usr/bin/env python3
"""录音机 · 最小原型：WorkBuddy 会话 → pi 会话（只搬 user/assistant 文本）。

刻意的取舍（用户定的范围）：
  · 源**只读**，一个字节都不改；
  · 不实时，脚本离线跑；
  · 只搬 user / assistant 的文本；工具调用、思考、附件一律不搬；
  · 目标只用"产品自己的格式"，不给它任何私货。

产出：一个 pi 的 jsonl —— header(v3) + 一条线性 id 链的 message 条目。
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, timezone

WRAPPER = re.compile(r"^\s*<([a-zA-Z][\w-]*)(?:\s[^>]*)?>.*?</\1>\s*", re.DOTALL)
USER_QUERY = re.compile(r"<user_query>(.*?)</user_query>", re.DOTALL)


def clean_user_text(t: str) -> str:
    """剥掉平台注入的包裹块，只留人写的那句话（有 <user_query> 就取它的内容）。"""
    m = USER_QUERY.search(t)
    if m:
        return m.group(1).strip()
    out = t
    while True:
        mm = WRAPPER.match(out)
        if not mm:
            return out.strip()
        out = out[mm.end():]


def texts_of(obj: dict) -> list[str]:
    c = obj.get("content")
    out = []
    if isinstance(c, str):
        return [c]
    if isinstance(c, list):
        for x in c:
            if not isinstance(x, dict):
                continue
            if x.get("type") in ("input_text", "output_text", "text") and x.get("text"):
                out.append(x["text"])
    return out


def main() -> int:
    src, dst, cwd = sys.argv[1], sys.argv[2], sys.argv[3]
    new_id = str(uuid.uuid4())

    rows = []
    with open(src, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") != "message":
                continue
            role = o.get("role")
            if role not in ("user", "assistant"):
                continue
            text = "\n".join(texts_of(o)).strip()
            if not text:
                continue
            if role == "user":
                text = clean_user_text(text)
                if not text:
                    continue
            ts_ms = o.get("timestamp") or 0
            rows.append((role, text, ts_ms))

    if not rows:
        print("源会话里没有可搬的 user/assistant 文本", file=sys.stderr)
        return 1

    first_ms = rows[0][2] or int(datetime.now(timezone.utc).timestamp() * 1000)
    header = {
        "type": "session", "version": 3, "id": new_id,
        "timestamp": datetime.fromtimestamp(first_ms / 1000, timezone.utc)
                              .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "cwd": cwd,
    }

    zero_usage = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0,
                  "totalTokens": 0,
                  "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}

    lines = [json.dumps(header, ensure_ascii=False)]
    parent = None
    for i, (role, text, ts_ms) in enumerate(rows, 1):
        eid = f"{i:08x}"
        iso = datetime.fromtimestamp((ts_ms or first_ms) / 1000, timezone.utc) \
                       .isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if role == "user":
            msg = {"role": "user", "content": text, "timestamp": ts_ms or first_ms}
        else:
            msg = {"role": "assistant",
                   "content": [{"type": "text", "text": text}],
                   "api": "migrated", "provider": "migrated", "model": "migrated",
                   "usage": zero_usage, "stopReason": "stop",
                   "timestamp": ts_ms or first_ms}
        lines.append(json.dumps({"type": "message", "id": eid, "parentId": parent,
                                 "timestamp": iso, "message": msg}, ensure_ascii=False))
        parent = eid

    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"写出 {dst}: header + {len(rows)} 条消息（user {sum(1 for r in rows if r[0]=='user')} / "
          f"assistant {sum(1 for r in rows if r[0]=='assistant')}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
