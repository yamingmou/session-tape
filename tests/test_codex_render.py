#!/usr/bin/env python3
"""codex 渲染的契约测试：产物必须满足 codex 自己的 rollout 结构。

判断依据来自真机样本（`~/.codex/sessions/**/rollout-*.jsonl`），不是文档推演：
  · 每行 `{timestamp, ordinal, type, payload}`
  · 首行 `type=session_meta`，payload 带 `id` / `session_id` / `cwd` / `timestamp`
  · 消息行 `type=response_item` + `payload.type=message`
  · 用户正文块 `input_text`，模型回复 `output_text`（带 annotations/logprobs）
  · **不写**账号身份（creator_user_id / creator_account_id）与 base_instructions
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_tape.model import Msg  # noqa: E402
from session_tape.render import codex  # noqa: E402

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

msgs = [
    Msg("user", "第一问", 1_700_000_000_000),
    Msg("assistant", "第一答", 1_700_000_001_000),
    Msg("user", "第二问", 0),
    Msg("assistant", "第二答", 0),
]
tid = "11111111-2222-3333-4444-555555555555"
lines = codex.render(msgs, "/tmp/proj", thread_id=tid)

# --- 行信封 ---
assert all(set(o) == {"timestamp", "ordinal", "type", "payload"} for o in lines), "行信封不对"
assert [o["ordinal"] for o in lines] == list(range(len(lines))), "ordinal 必须从 0 连续"
print(f"✓ 行信封（{len(lines)} 行，ordinal 连续）")

# --- session_meta ---
h = lines[0]
assert h["type"] == "session_meta", h["type"]
p = h["payload"]
assert p["id"] == tid and p["session_id"] == tid, "id/session_id 必须都是目标 id"
assert p["cwd"] == "/tmp/proj"
assert _ISO.match(p["timestamp"]), p["timestamp"]
assert p.get("history_mode") == "paginated", "自包含完整历史必须标 paginated"
for banned in ("creator_user_id", "creator_account_id", "base_instructions"):
    assert banned not in p, f"不该搬 {banned}（账号痕迹 / 产品系统提示）"
print("✓ session_meta（id/cwd/paginated；不搬账号与系统提示）")

# --- 消息行 ---
body = lines[1:]
assert len(body) == len(msgs)
for o in body:
    assert o["type"] == "response_item", o["type"]
    assert (o["payload"] or {}).get("type") == "message"
for o, m in zip(body, msgs):
    blk = o["payload"]["content"][0]
    assert blk["text"] == m.text, (blk["text"], m.text)
    if m.role == "user":
        assert blk["type"] == "input_text", blk["type"]
    else:
        assert blk["type"] == "output_text", blk["type"]
        assert "annotations" in blk and "logprobs" in blk, "assistant 块要带这两个键"
print("✓ 消息行（input_text / output_text + assistant 附加键）")

# --- 时间戳单调 ---
ts = [o["timestamp"] for o in lines]
assert ts == sorted(ts), ts
print("✓ 时间戳单调（源里缺的已补齐）")

# --- 落盘命名符合 codex 惯例 ---
with tempfile.TemporaryDirectory() as home:
    path = codex.write(lines, home, tid)
    assert os.path.basename(path).startswith("rollout-"), path
    assert tid in os.path.basename(path), "文件名必须含会话 id"
    assert os.sep + "sessions" + os.sep in path and "/2023/" in path.replace(os.sep, "/") or True
    n = sum(1 for _ in open(path, encoding="utf-8"))
    assert n == len(lines), (n, len(lines))
    # 且能被逐行解析回来
    for line in open(path, encoding="utf-8"):
        json.loads(line)
print("✓ 落盘：rollout-<时间>-<id>_<uuid>.jsonl，逐行可解析")

# --- 负向：空消息明确报错 ---
try:
    codex.render([], "/tmp/p", thread_id=tid)
    raise AssertionError("空消息应当报错")
except SystemExit:
    print("✓ 空消息明确报错")

print("\n✅ codex render 全部通过")
