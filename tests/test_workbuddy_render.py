#!/usr/bin/env python3
"""WorkBuddy 渲染的契约测试。

判断依据来自真机样本（`~/.workbuddy/projects/**/*.jsonl`）：
  · 每行 `{id, parentId, timestamp(ms), type:"message", role, content:[{type,text}]}`
  · id 是 uuid 形态，`parentId` 串成一条链（首条为 null）
  · 用户正文块 `input_text`，模型回复 `output_text`
  · `timestamp` 是**毫秒整数**（不是 ISO 字符串——这点与 codex 相反，别抄错）
"""
import os
import re
import sys
import uuid as uuidlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_tape.model import Msg        # noqa: E402
from session_tape.render import workbuddy as wb  # noqa: E402

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

msgs = [
    Msg("user", "第一问", 1_700_000_000_000),
    Msg("assistant", "第一答", 1_700_000_001_000),
    Msg("user", "第二问", 0),
]
lines = wb.render(msgs, "/tmp/proj")

assert len(lines) == len(msgs), (len(lines), len(msgs))
for i, (o, m) in enumerate(zip(lines, msgs)):
    assert set(o) == {"id", "parentId", "timestamp", "type", "role", "content"}, sorted(o)
    assert _UUID.match(o["id"]), o["id"]
    assert o["type"] == "message" and o["role"] == m.role
    assert isinstance(o["timestamp"], int), "WorkBuddy 的时间戳是毫秒整数，不是 ISO"
    blk = o["content"][0]
    assert blk["text"] == m.text
    assert blk["type"] == ("input_text" if m.role == "user" else "output_text")
    if i == 0:
        assert o["parentId"] is None, "首条 parentId 必须是 null"
    else:
        assert o["parentId"] == lines[i - 1]["id"], "parentId 必须串成链"
    assert "providerData" not in o, "不搬 providerData（模型实现痕迹）"
print("✓ 行结构（uuid id / 链式 parentId / 毫秒时间戳 / 无 providerData）")

ts = [o["timestamp"] for o in lines]
assert ts == sorted(ts) and len(set(ts)) == len(ts), ts
print("✓ 时间戳单调且不重复（缺的已补齐）")

# 负向：空消息报错
try:
    wb.render([], "/tmp/p")
    raise AssertionError("空消息应当报错")
except SystemExit:
    print("✓ 空消息明确报错")

# 项目目录按 cwd 推导（与产品的路径逻辑一致）
assert wb._slug("/Users/a/临时用") == "Users-a-临时用", wb._slug("/Users/a/临时用")
assert wb._slug("/") == "migrated"
print("✓ 项目目录名按 cwd 推导")

print("\n✅ workbuddy render 全部通过")
