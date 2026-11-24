"""目标产品的渲染器。一个目标一个文件。

每个目标的接口约定（缺一不可，因为不同产品的"落地"差别很大）：
  `render(msgs, cwd, **kw)`   → 中间产物（文件文本 / 行序列）
  `write(payload, out, **kw)` → 落盘，返回路径
  `register(path, **kw)`      → 可选：让产品**认识**这条会话（DB 型产品必须，文件型不需要）

为什么不让渲染器直接写盘：验收要能分开做——
先看"产物长什么样"（纯函数、可测），再看"产品认不认"（必须真机）。

共同点（不满足产品就读不了）：
  ① 容器头部合法（会话 id / 版本 / cwd / 时间）；
  ② 每条消息用**目标产品自己的 id 形态**，连成它认识的结构（链或树）；
  ③ 时间戳单调。
差异点（唯一不能靠"复制前缀"解决）：**id 链必须重造**。
"""
from __future__ import annotations

from . import claude, codex, hermes, openclaw, pi, workbuddy

TARGETS = {
    "pi": pi,
    "codex": codex,
    "workbuddy": workbuddy,
    "claude-code": claude, "claude": claude,
    "hermes": hermes,
    "openclaw": openclaw,
}


def module(to: str):
    if to not in TARGETS:
        raise SystemExit(f"✗ 还不支持目标 {to}；目前支持：{', '.join(sorted(set(TARGETS)))}")
    return TARGETS[to]
