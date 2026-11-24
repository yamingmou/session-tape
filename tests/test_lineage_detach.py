#!/usr/bin/env python3
"""谱系摘除测试：迁移不该留下"我是某条会话的分支"的边。

为什么这条值得单独测：`register_branch` 是给"打分支"用的，它会顺手写一条谱系边。
迁移复用它，就会把新会话错误地挂到模板会话下面——而**有些产品会让归档态沿谱系继承**，
模板一旦被归档，我们的迁移产物会被一起当成归档态。

判据三条：只摘自己那一条 / 别人的一条不动 / 重复调用是幂等的（返回 False）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_tape.render._lineage import detach  # noqa: E402

NEW = "new-session-id"


class _Fake:
    def __init__(self, data):
        self._data = data
        self.writes = 0

    def _read_index(self):
        return self._data

    def _write_index(self, data):
        self._data = data
        self.writes += 1


# ① 只摘自己那一条，别人的保持原样
fake = _Fake({"branches": [
    {"id": "other-1", "name": "别人的分支"},
    {"id": NEW, "name": "迁移产物"},
    {"id": "other-2", "name": "别人的分支"},
]})
assert detach(fake, NEW) is True
assert [b["id"] for b in fake._data["branches"]] == ["other-1", "other-2"], fake._data
print("✓ 只摘自己那一条，其余两条原样保留")

# ② 幂等：再摘一次返回 False，且不再写盘
before = fake.writes
assert detach(fake, NEW) is False
assert fake.writes == before, "不该重复写盘"
print("✓ 幂等（第二次返回 False 且不写盘）")

# ③ 没有谱系索引的适配器：不报错，返回 False
class _NoIndex:
    pass

assert detach(_NoIndex(), NEW) is False
print("✓ 适配器没有 JSON 谱系索引时安全返回 False")

# ④ 结构异常（branches 不是列表）也不炸
assert detach(_Fake({"branches": "oops"}), NEW) is False
print("✓ 结构异常时不炸")

print("\n✅ 谱系摘除通过")
