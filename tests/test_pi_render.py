#!/usr/bin/env python3
"""pi 渲染的契约测试：产物必须满足 pi 自己的格式文档（docs/session-format.md）。

判断依据逐条对应文档，不是我自己想的：
  · header  `type=session` / `version=3` / `id` 是 uuid / `timestamp` ISO / `cwd`
  · 条目    `type=message` / `id` 是 **8 位 hex** / `parentId` 为 null 或指向前面某条
  · assistant 外壳必须有 `provider` / `model` / `usage` / `stopReason`
  · 线性链：第 1 条 parentId 为 null，其后每条指向紧邻的前一条
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_tape.model import Msg              # noqa: E402
from session_tape.render import pi as pi_render  # noqa: E402

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_HEX8 = re.compile(r"^[0-9a-f]{8}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

msgs = [
    Msg("user", "第一问", 1_700_000_000_000),
    Msg("assistant", "第一答", 1_700_000_001_000),
    Msg("user", "第二问", 0),                      # 源里没时间戳 ⇒ 渲染时要按顺序补
    Msg("assistant", "第二答", 0),
]
text = pi_render.render(msgs, "/tmp/proj")
lines = [json.loads(x) for x in text.strip().split("\n")]
assert text.endswith("\n"), "文件末尾要有换行"

# --- header ---
h = lines[0]
assert h["type"] == "session", h
assert h["version"] == 3, h
assert _UUID.match(h["id"]), h["id"]
assert _ISO.match(h["timestamp"]), h["timestamp"]
assert h["cwd"] == "/tmp/proj", h
print("✓ header（type/version/uuid/ISO/cwd）")

# --- 条目 ---
entries = lines[1:]
assert len(entries) == len(msgs), (len(entries), len(msgs))
parent = None
for i, e in enumerate(entries, 1):
    assert e["type"] == "message", e
    assert _HEX8.match(e["id"]), e["id"]
    assert e["id"] == f"{i:08x}", e["id"]                # 递增，可复现
    assert e["parentId"] == parent, (e["id"], e["parentId"], parent)
    assert _ISO.match(e["timestamp"]), e["timestamp"]
    parent = e["id"]
print("✓ 条目：8 位 hex id + 线性 parentId 链 + ISO 时间戳")

# --- 角色外壳 ---
u, a = entries[0]["message"], entries[1]["message"]
assert u["role"] == "user" and isinstance(u["content"], str), u
assert a["role"] == "assistant", a
assert isinstance(a["content"], list) and a["content"][0]["type"] == "text", a["content"]
for k in ("provider", "model", "usage", "stopReason", "api"):
    assert k in a, f"assistant 缺必填外壳字段 {k}"
assert set(a["usage"]) >= {"input", "output", "totalTokens", "cost"}, a["usage"]
print("✓ assistant 外壳（provider/model/usage/stopReason/api）")

# --- 时间戳单调（源里两条是 0，必须被补齐成递增）---
ts = [e["timestamp"] for e in entries]
assert ts == sorted(ts), ts
assert ts[2] > ts[1] and ts[3] > ts[2], ts
print(f"✓ 时间戳单调（缺省的被补齐：{ts[1]} → {ts[2]} → {ts[3]}）")

# --- 负向：空消息要明确报错，不能产出空壳会话 ---
try:
    pi_render.render([], "/tmp/proj")
    raise AssertionError("空消息应当报错")
except SystemExit:
    print("✓ 空消息明确报错（不产出空壳）")

# --- 负向：正文里的换行/引号必须原样保留（JSON 转义正确）---
tricky = '第一行\n第二行 "引号" \\ 反斜杠'
one = json.loads(pi_render.render([Msg("user", tricky, 1)], "/tmp/p").strip().split("\n")[1])
assert one["message"]["content"] == tricky, one["message"]["content"]
print("✓ 特殊字符原样保留（换行/引号/反斜杠）")

print("\n✅ pi render 全部通过")
