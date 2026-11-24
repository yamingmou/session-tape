"""易用性：让不知道会话 id 的人也能用。

三个入口，从"完全不懂"到"完全可控"：

  `session-tape`          → 向导：问你要从哪搬到哪，替你拼参数
  `session-tape list`     → 列出本机有哪些会话（带编号，不用记 id）
  `session-tape demo`     → 离线演示：不需要装任何产品，也不用真会话

复杂参数一个都没删——向导只是**生成**它们，不是替代它们。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

from . import render
from .model import Msg
from .source import _load_fork_core

SOURCES = ["workbuddy", "claude-code", "codex", "hermes", "pi", "openclaw"]
TARGETS = ["pi", "codex", "workbuddy", "claude-code", "hermes", "openclaw"]

#: 有数据才值得列（各产品的家目录；没有就跳过）
HOME_HINTS = {
    "workbuddy": "~/.workbuddy",
    "claude-code": "~/.claude",
    "codex": "~/.codex",
    "hermes": "~/.hermes",
    "pi": "~/.pi",
    "openclaw": "~/.openclaw",
}


def _has_home(product: str) -> bool:
    return os.path.isdir(os.path.expanduser(HOME_HINTS.get(product, "")))


def _fmt_time(ts: float | None) -> str:
    if not ts:
        return "  -  "
    return time.strftime("%m-%d %H:%M", time.localtime(ts))


def list_sessions(product: str, limit: int = 15) -> list[tuple[str, float, int]]:
    """返回 [(session_id, mtime, 字节数)]，按最近修改倒序。"""
    adapters = _load_fork_core()
    ad = adapters.get_adapter(product)
    rows = []
    for path, sid in ad.list_all_sessions():
        try:
            st = os.stat(path)
        except OSError:
            continue
        rows.append((sid, st.st_mtime, st.st_size))
    rows.sort(key=lambda r: -r[1])
    return rows[:limit]


def cmd_list(argv: list[str]) -> int:
    products = [a for a in argv if not a.startswith("-")] or SOURCES
    for product in products:
        if not _has_home(product):
            continue
        try:
            rows = list_sessions(product)
        except Exception as e:
            print(f"\n{product}: 读不了（{e}）")
            continue
        print(f"\n{product}  （{len(rows)} 条，最近的在前）")
        for i, (sid, mtime, size) in enumerate(rows, 1):
            print(f"  {i:2}. {_fmt_time(mtime)}  {size // 1024:>6} KB  {sid}")
    print("\n搬到别处：session-tape --from <产品> --session <上面的 id> --to <目标> --out <位置>")
    print("或用向导：直接敲 session-tape")
    return 0


def cmd_demo() -> int:
    """离线演示：造 4 条消息，渲染到每个目标，打印产物形状。不需要任何产品。"""
    msgs = [Msg("user", "你好，我们之前聊到要把这套流程搬到别的工具里", 1_700_000_000_000),
            Msg("assistant", "对，先只搬对话文本：工具调用和附件不动", 1_700_000_001_000),
            Msg("user", "那怎么确认搬成功了", 1_700_000_002_000),
            Msg("assistant", "让目标工具自己读一遍，并且真的接着聊一轮", 1_700_000_003_000)]
    print(f"演示数据：{len(msgs)} 条消息（2 问 2 答）\n")
    print(f"{'目标':14}{'产物':10}{'落在哪（临时目录）'}")
    print("-" * 72)
    for name in TARGETS:
        try:
            mod = render.module(name)
        except SystemExit:
            continue
        tmp = tempfile.mkdtemp(prefix=f"tape-demo-{name}-")
        try:
            if name == "pi":
                text = mod.render(msgs, tmp)
                path = os.path.join(tmp, "session.jsonl")
                open(path, "w", encoding="utf-8").write(text)
                shape = f"{text.count(chr(10))} 行"
            elif name == "codex":
                lines = mod.render(msgs, tmp, thread_id="11111111-2222-3333-4444-555555555555")
                path = mod.write(lines, tmp, "11111111-2222-3333-4444-555555555555")
                shape = f"{len(lines)} 行"
            elif name == "workbuddy":
                lines = mod.render(msgs, tmp, session_id="22222222-3333-4444-5555-666666666666")
                path = mod.write(lines, tmp, "22222222-3333-4444-5555-666666666666", cwd=tmp)
                shape = f"{len(lines)} 条"
            elif name in ("claude-code", "claude"):
                lines = mod.render(msgs, tmp, session_id="33333333-4444-5555-6666-777777777777")
                path = mod.write(lines, tmp, "33333333-4444-5555-6666-777777777777", cwd=tmp)
                shape = f"{len(lines)} 条"
            elif name == "openclaw":
                lines = mod.render(msgs, tmp, session_id="44444444-5555-6666-7777-888888888888")
                path = mod.write(lines, tmp, "44444444-5555-6666-7777-888888888888")
                shape = f"{len(lines)} 行"
            else:      # hermes 需要真库，演示只标出来
                print(f"{name:14}{'（需库）':10}跳过：这一家的写入需要一个真实 state.db 当模板")
                continue
            print(f"{name:14}{shape:10}{path.replace(tmp, '…')}")
        except SystemExit as e:
            # 缺依赖不该把表格撑乱：压缩成一行并给出修复入口
            short = "需要 session-fork-core（这一家的写入要经过适配器）" \
                if "session-fork-core" in str(e) else str(e).split("\n")[0]
            print(f"{name:14}{'跳过':10}{short}")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
    print("\n上面每一份都是**目标产品格式**的完整会话。真实迁移时，把它放进那个产品的家目录，")
    print("再让产品自己打开——我们不以自己的断言为准。")
    return 0


def wizard() -> int:
    """交互向导：问三个问题，然后按现有参数跑。"""
    avail = [p for p in SOURCES if _has_home(p)]
    if not avail:
        print("没找到任何产品的会话目录。")
        print("可以先用演示看效果：session-tape demo")
        return 1

    print("从哪个产品搬？（本机找到的）")
    for i, p in enumerate(avail, 1):
        print(f"  {i}. {p}")
    src = _ask_choice(avail, "序号", default=1)
    if src is None:
        return 1

    rows = list_sessions(src)
    if not rows:
        print(f"{src} 里没有找到会话。")
        return 1
    print(f"\n{src} 的会话（最近 {len(rows)} 条）：")
    for i, (sid, mtime, size) in enumerate(rows, 1):
        print(f"  {i:2}. {_fmt_time(mtime)}  {size // 1024:>6} KB  {sid}")
    idx = _ask_index(len(rows), "要搬第几条", default=1)
    if idx is None:
        return 1
    sid = rows[idx][0]

    print("\n搬到哪个产品？")
    for i, t in enumerate(TARGETS, 1):
        print(f"  {i}. {t}")
    dst = _ask_choice(TARGETS, "序号", default=1)
    if dst is None:
        return 1

    name = input("\n标题（回车用默认）：").strip() or f"从 {src} 迁移"

    # 大会话预警：几百条以上搬过去会很大，也可能不是用户想要的那段
    mtime_size = rows[idx][2]
    if mtime_size > 2 * 1024 * 1024:
        print(f"\n⚠ 这条会话有 {mtime_size // 1024 // 1024} MB —— 搬过去会很大。"
              f"如果只想接着最近一段聊，可以只搬最后几轮（--limit N）。")
        lim = input("只搬最后几轮？（回车=全搬）：").strip()
        if lim.isdigit():
            args_limit = ["--limit", lim]
        else:
            args_limit = []

    # 目标相关的落地细节
    args = ["--from", src, "--session", sid, "--to", dst, "--name", name] + locals().get("args_limit", [])
    if dst == "codex":
        shell = input("要在界面里先 fork 一条吗？把它的 id 粘进来（回车则自己造壳）：").strip()
        if shell:
            args += ["--fill", shell]
        else:
            home = input("CODEX_HOME（回车用 ~/.codex）：").strip() or os.path.expanduser("~/.codex")
            args += ["--install-codex-home", home]
    elif dst == "workbuddy":
        print("⚠ 这会写进 WorkBuddy 的真实库。建议先复制一份库再试。")
        home = input("WorkBuddy home（含 workbuddy.db 与 projects/，回车用 ~/.workbuddy）：").strip() \
            or os.path.expanduser("~/.workbuddy")
        args += ["--install-wb-home", home]
    elif dst == "hermes":
        db = input("state.db 路径（回车用 ~/.hermes/state.db）：").strip() \
            or os.path.expanduser("~/.hermes/state.db")
        args += ["--out", db]
    elif dst in ("claude-code", "claude"):
        out = input("~/.claude 路径（回车用默认）：").strip() or os.path.expanduser("~/.claude")
        args += ["--out", out]
    elif dst == "openclaw":
        out = input("~/.openclaw 路径（回车用默认）：").strip() or os.path.expanduser("~/.openclaw")
        args += ["--out", out]
    else:  # pi
        out = input("pi 的 sessions 目录（回车用 ~/.pi/agent/sessions）：").strip() \
            or os.path.expanduser("~/.pi/agent/sessions")
        args += ["--out", out]

    print("\n将执行：")
    print("  session-tape " + " ".join(args))
    if input("确认？[Y/n] ").strip().lower() in ("n", "no"):
        print("已取消。")
        return 1
    from .cli import main as cli_main
    return cli_main(args)


def _ask_choice(options: list[str], label: str, default: int = 1):
    raw = input(f"{label} [{default}]：").strip()
    if not raw:
        return options[default - 1] if 0 < default <= len(options) else None
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    print("没听懂这个序号，退出。")
    return None


def _ask_index(n: int, label: str, default: int = 1):
    raw = input(f"{label} [{default}]：").strip()
    if not raw:
        return default - 1 if n >= default else None
    if raw.isdigit() and 1 <= int(raw) <= n:
        return int(raw) - 1
    print("没听懂这个序号，退出。")
    return None
