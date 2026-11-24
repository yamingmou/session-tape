#!/usr/bin/env python3
"""投影/消费进度断言：**"产品可见"的可自动检查代理指标**。

背景：我们没法自动断言"它出现在产品列表里"——那要跑产品自己的 UI 与索引逻辑。
但有一条是能读的：产品记着"这条 rollout 我消费到第 N 字节"。若 N>0，我们新写的内容
永远不会被解析，界面就是空的或旧内容。

所以断言 `(0,0)`。注意口径：**代理指标通过 ≠ 产品可见；但它失败就一定看不见。**
（这条来自上游踩坑记录的接口边界：不承诺"写进去就能看见"。）

本测试自带一个最小库，不依赖本机装没装 codex，因此能在 CI 里跑。
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_tape.render import codex  # noqa: E402

TID = "11111111-2222-3333-4444-555555555555"


class _FakeAdapter:
    """只提供 _connect 与 HISTORY_DB —— 断言函数只需要这两样。"""

    def __init__(self, path):
        self.HISTORY_DB = path

    def _connect(self, db):
        return sqlite3.connect(db)


def _mkdb(offset=0, ordinal=0, row=True):
    d = tempfile.mkdtemp(prefix="proj-")
    path = os.path.join(d, "thread_history_1.sqlite")
    con = sqlite3.connect(path)
    con.execute("create table thread_history_projection_state "
                "(thread_id text primary key, next_rollout_byte_offset integer, "
                "next_rollout_ordinal integer)")
    if row:
        con.execute("insert into thread_history_projection_state values (?,?,?)",
                    (TID, offset, ordinal))
    con.commit()
    con.close()
    return path


# ① 初始值 ⇒ 通过，并回读为 (0,0)
ok = codex._assert_projection_zero(_FakeAdapter(_mkdb()), TID)
assert ok == (0, 0), ok
print("✓ 投影为 (0,0) 时通过")

# ② 非初始值 ⇒ 必须报错（否则"文件写对了但界面空"会被静默放过）
for off, ordn in ((999, 7), (1, 0), (0, 3)):
    try:
        codex._assert_projection_zero(_FakeAdapter(_mkdb(off, ordn)), TID)
        raise AssertionError(f"({off},{ordn}) 应当报错")
    except SystemExit as e:
        assert "投影状态不是初始值" in str(e), str(e)
print("✓ 非初始值一律报错（覆盖三种非零组合）")

# ③ 状态行缺失 ⇒ 必须报错（比非零更糟：产品连"消费到哪"都不知道）
try:
    codex._assert_projection_zero(_FakeAdapter(_mkdb(row=False)), TID)
    raise AssertionError("缺行应当报错")
except SystemExit as e:
    assert "找不到投影状态行" in str(e), str(e)
print("✓ 状态行缺失时明确报错")

print("\n✅ 投影断言通过（代理指标口径：通过≠可见，失败一定不可见）")
