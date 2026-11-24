"""本仓库自持的引擎（不在 session-fork-core 覆盖范围内的产品）。

每个引擎提供：`find_db()` / `list_sessions()` / `read_msgs()` / `write_msgs()`。
加一个产品的真实成本就是这四个函数 + 一份契约测试。
"""
from . import opencode

ENGINES = {"opencode": opencode}


def get(name: str):
    if name not in ENGINES:
        raise SystemExit(f"✗ 还没有这个引擎：{name}；目前：{', '.join(sorted(ENGINES))}")
    return ENGINES[name]
