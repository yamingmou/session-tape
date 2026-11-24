"""依赖兜底：`session-fork-core` 是读侧与部分写侧的依赖。

两种到场方式都要支持：
  · 已 `pip install`（正常安装路径）；
  · 开发期用环境变量 `FORK_CORE_PATH` 指向本地检出（不必先装）。

统一在这里处理，避免每个模块各写一遍 `sys.path` 操作——那样一旦漏一处，
表现是"某个目标突然说找不到模块"，很难查。
"""
from __future__ import annotations

import os
import sys


class MissingDependency(SystemExit):
    """缺依赖时抛这个：带可执行的修复指令，而不是一段栈回溯。"""

    def __init__(self) -> None:
        super().__init__(
            "✗ 需要 session-fork-core（读产品会话的适配器层）：\n"
            '  pip install "git+https://github.com/yamingmou/session-fork-core.git"\n'
            "  或设置 FORK_CORE_PATH=<本地检出路径> 后再跑"
        )


def ensure_fork_core():
    """返回 `fork_core` 模块；拿不到就抛 MissingDependency。"""
    try:
        import fork_core
        return fork_core
    except ImportError:
        pass
    path = os.environ.get("FORK_CORE_PATH")
    if path and os.path.isdir(path):
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            import fork_core
            return fork_core
        except ImportError:
            pass
    raise MissingDependency()


def has_fork_core() -> bool:
    try:
        ensure_fork_core()
        return True
    except SystemExit:
        return False
