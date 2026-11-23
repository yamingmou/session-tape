"""读源：调 session-fork-core 的适配器，把任意支持产品的历史读成 `Msg` 序列。

刻意**不复制**读侧代码：那六个适配器是逐个真机验过的（schema 白名单、压缩事件、
排队形态指令……每一条都付过代价）。这里只做"适配器 → 规范化模型"的转换。
"""
from __future__ import annotations

import os

from .model import Msg, Source


def _load_fork_core():
    """拿到 fork_core 的 adapters。装不上就给出可执行的修复建议，而不是栈回溯。"""
    try:
        from fork_core import adapters as fork_adapters   # type: ignore
        return fork_adapters
    except Exception:
        pass
    # 开发期便利：允许用环境变量指向本地工作副本
    dev = os.environ.get("FORK_CORE_PATH")
    if dev:
        import sys
        if os.path.isdir(dev) and dev not in sys.path:
            sys.path.insert(0, dev)
        from fork_core import adapters as fork_adapters   # type: ignore
        return fork_adapters
    raise SystemExit(
        "✗ 读源需要 session-fork-core 的适配器，但没找到。\n"
        '  装：pip install "git+https://github.com/yamingmou/session-fork-core.git@v2.4.24"\n'
        "  或：FORK_CORE_PATH=<本地工作副本路径> 再跑一次"
    )


def _ts_of(obj: dict) -> int:
    """取毫秒时间戳。

    各产品字段与**类型**都不同：Codex/WorkBuddy 是毫秒整数，pi/Claude 是 ISO 字符串。
    只认数字会静默丢掉时间（实测：pi→codex 的链式迁移里时间全变 0，目录落到 1970）。
    """
    for k in ("timestamp", "ts", "created_at", "time"):
        v = obj.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v if v > 1e12 else v * 1000)
        if isinstance(v, str) and v.strip():
            s = v.strip().replace("Z", "+00:00")
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    from datetime import timezone
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)
            except Exception:
                continue
    return 0


def read(product: str, session_ref: str) -> Source:
    fork_adapters = _load_fork_core()
    adapter = fork_adapters.get_adapter(product)

    sid = adapter.resolve_session(session_ref)
    path, cwd = adapter.find_transcript(sid)
    if not path:
        raise SystemExit(f"✗ 找不到会话 {sid}（产品 {product}）")
    return _normalize(adapter, path, product, sid, cwd or "")


def read_file(product: str, path: str) -> Source:
    """**直接指定一个转录文件**，绕开"按 id 找"。

    为什么需要它：有的产品会话 id 是"线程级"的，跨多次运行共用（Codex 就是），
    按 id 取会拿到**最新那次运行**，不一定是你要搬的那次。这时只能按文件指定。
    """
    fork_adapters = _load_fork_core()
    adapter = fork_adapters.get_adapter(product)
    real = os.path.expanduser(path or "")
    if not real or not os.path.exists(real):
        raise SystemExit(f"✗ 转录文件不存在：{path}")
    return _normalize(adapter, real, product, "", "")


def _normalize(adapter, path: str, product: str, sid: str, cwd: str) -> Source:
    raw = adapter.read_lines(path)
    human = getattr(adapter, "is_human_turn", None)
    is_human = human if callable(human) else adapter.is_user_message

    msgs: list[Msg] = []
    for obj in raw:
        if is_human(obj):
            role = "user"
        elif adapter.is_assistant_message(obj):
            role = "assistant"
        else:
            continue                      # 工具结果、平台注入等：不搬（见 README「边界」）
        text = (adapter.get_text(obj) or "").strip()
        if not text:
            continue
        msgs.append(Msg(role=role, text=text, ts_ms=_ts_of(obj)))

    return Source(msgs=msgs, product=product, session_id=sid, cwd=cwd)
