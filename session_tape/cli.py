"""命令行：`session-tape --from <产品> --session <引用> --to <产品> --out <位置>`。

刻意做成一个**独立入口**（不是给 session-fork 加个参数）：
它的语义是"搬到另一个产品"，与"同一产品内打分支"的失败模式完全不同，
混在一个命令里会让帮助文本和风险描述都变形。

两个目标的"落地"不一样，所以接口分开：
  · **pi**：只写一个会话文件 —— `--out` 给目录或 `.jsonl` 路径；
  · **codex**：写 rollout **还要登记进产品库**，否则文件在但列表里看不见
    ⇒ `--install-codex-home <CODEX_HOME>` 指到产品主目录（缺省只产文件、不登记）。
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

from . import __version__, noise, render, source


def _pi_out(out: str) -> str:
    """pi 的 `--out`：目录就按它的命名惯例落一个文件；`.jsonl` 就直接用。"""
    if out.endswith(".jsonl"):
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        return out
    os.makedirs(out, exist_ok=True)
    import time
    return os.path.join(out, f"{time.strftime('%Y-%m-%dT%H-%M-%S')}_{uuid.uuid4()}.jsonl")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # 子命令分派（易用性入口；复杂参数一个没删）
    if argv and argv[0] == "list":
        from .ui import cmd_list
        return cmd_list(argv[1:])
    if argv and argv[0] == "demo":
        from .ui import cmd_demo
        return cmd_demo()
    if not argv:
        from .ui import wizard
        try:
            return wizard()
        except (KeyboardInterrupt, EOFError):
            print("\n已取消。")
            return 1

    ap = argparse.ArgumentParser(
        prog="session-tape",
        description="把一个产品的会话历史搬到另一个产品里继续（只搬文本历史，单向）",
        epilog="不知道从哪下手？直接敲 session-tape（向导），或 session-tape list / session-tape demo",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--from", dest="src", default="workbuddy",
                    help="源产品（workbuddy / claude-code / codex / hermes / pi / openclaw）")
    ap.add_argument("--session", help='源会话引用（id，或 "current"）；与 --session-file 二选一')
    ap.add_argument("--session-file", help="直接指定转录文件（用于 id 有歧义的产品，如 Codex 的线程级 id）")
    ap.add_argument("--to", dest="dst", default="pi", help="目标产品（pi / codex / workbuddy / claude-code / hermes / openclaw / opencode）")
    ap.add_argument("--out", help="输出位置：目录（按目标惯例命名）或 .jsonl 路径")
    ap.add_argument("--install-codex-home", help="把会话登记进这个 CODEX_HOME（让 codex 列表里看得见）")
    ap.add_argument("--install-wb-home", help="把会话登记进这个 WorkBuddy home（含 workbuddy.db 与 projects/）")
    ap.add_argument("--project", default="", help="workbuddy 目标：写进哪个项目目录（缺省 migrated）")
    ap.add_argument("--fill", help="官方建壳、我们灌内容：把历史写进这条已存在的 codex 会话（id 保持不变）")
    ap.add_argument("--cwd", default="", help="写进目标会话的 cwd（缺省用源的 cwd）")
    ap.add_argument("--name", default="", help="分支/会话标题（写进目标的标题字段）")
    ap.add_argument("--limit", type=int, default=0, help="只搬最后 N 条（0=全部）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不落盘")
    args = ap.parse_args(argv)

    if bool(args.session) == bool(args.session_file):
        ap.error("--session 与 --session-file 必须且只能给一个")
    if args.dst == "codex" and not (args.out or args.install_codex_home or args.fill):
        ap.error("codex 目标需要 --out（产文件）或 --install-codex-home（登记进产品）")
    if args.dst in ("claude-code", "claude") and not args.out:
        ap.error("claude-code 目标需要 --out（指向 ~/.claude 或它的替身目录）")
    if args.dst == "workbuddy" and not (args.out or args.install_wb_home):
        ap.error("workbuddy 目标需要 --out（产文件）或 --install-wb-home（登记进产品）")
    if args.dst == "pi" and not args.out:
        ap.error("pi 目标需要 --out")

    src = source.read_file(args.src, args.session_file) if args.session_file \
        else source.read(args.src, args.session)

    raw_n = len(src)
    stats: dict[str, int] = {}
    msgs = noise.clean(src.msgs, stats)
    if args.limit and len(msgs) > args.limit:
        # 截取必须落在"人说的话"上：往前扩到最近的 user 起点（不是往后丢）。
        # 实测教训：往后丢会切出"纯 assistant"的会话——既不像一次对话，产品也可能显示得很怪。
        start = len(msgs) - args.limit
        while start > 0 and msgs[start].role != "user":
            start -= 1
        msgs = msgs[start:]

    print(f"源      : {src.product} / {src.session_id or '(按文件)'}")
    print(f"读到    : {raw_n} 条消息")
    for k, v in stats.items():
        print(f"  丢掉  : {k} × {v}")
    if not any(m.role == "user" for m in msgs):
        raise SystemExit("✗ 截取后没有任何'人说的话'——请把 --limit 调大，或不加")
    print(f"待搬    : {len(msgs)} 条（user {sum(1 for m in msgs if m.role == 'user')} / "
          f"assistant {sum(1 for m in msgs if m.role == 'assistant')}）")

    if args.dry_run:
        print("（--dry-run：未落盘）")
        return 0

    cwd = args.cwd or src.cwd or os.getcwd()
    # pi 实测会拒绝打开"cwd 不存在"的会话（Stored session working directory does not exist）
    # ⇒ 源里记的 cwd 在本机不存在时，退回当前目录并明说，不要让用户面对一句产品报错。
    if not os.path.isdir(cwd):
        if args.cwd:
            # 用户**明确指定**的目录：建出来（他说要放那儿，就放那儿）
            os.makedirs(cwd, exist_ok=True)
            print(f"注意    : --cwd 指定的目录不存在，已创建 {cwd}")
        else:
            # 从源里**推导**出来的目录：本机可能没有（源在另一台机器/另一个路径）
            fallback = os.getcwd()
            print(f"注意    : 源记录的 cwd 在本机不存在（{cwd}）⇒ 改用当前目录 {fallback}")
            cwd = fallback

    title = args.name or "（迁移）"

    # ---- opencode（库型：两代存储都补）----
    if args.dst == "opencode":
        from . import engines
        eng = engines.get("opencode")
        db = os.path.expanduser(args.out) if args.out else eng.find_db()
        if not db or not os.path.exists(db):
            ap.error("opencode 目标需要 --out 指向 opencode.db（建议先复制一份再试）")
        sid = eng.write_msgs(msgs, db, title=title, cwd=cwd)
        back = eng.read_msgs(db, sid)
        print(f"会话 id : {sid}")
        print(f"写入    : {db}")
        print(f"产物    : {len(back)} 条读回（旧一代 session/message/part + 新一代 session_v2/session_message 都补）")
        print("注意    : 产品能否在界面列出未验（本机没有 opencode CLI）——属 L2")
        return 0

    mod = render.module(args.dst)

    if args.dst == "pi":
        text = mod.render(msgs, cwd, title=title)
        path = _pi_out(args.out)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"写到    : {path}")
        print(f"产物    : {text.count(chr(10))} 行，{len(text.encode('utf-8'))} 字节")
        print("验收    : lab/verify.mjs <文件>  /  scripts/verify_gate_pi.py --pi <pi> --session <文件>")
        return 0

    # ---- hermes（库型：行写进 sessions + messages）----
    if args.dst == "hermes":
        if not args.out:
            ap.error("hermes 目标需要 --out 指向 state.db（建议先复制一份再试）")
        sid = "20261124_" + uuid.uuid4().hex[:12]
        rows = mod.render(msgs, sid)
        ref = mod.write(rows, args.out, sid)
        print(f"会话 id : {sid}")
        print(f"写入    : {ref}")
        print(f"产物    : {len(rows)} 条消息（走适配器的事务链路）")
        return 0

    # ---- openclaw（与 pi 同形）----
    if args.dst == "openclaw":
        if not args.out:
            ap.error("openclaw 目标需要 --out 指向 ~/.openclaw 或它的替身目录")
        sid = str(uuid.uuid4())
        lines = mod.render(msgs, cwd, title=title, session_id=sid)
        path = mod.write(lines, args.out, sid)
        print(f"会话 id : {sid}")
        print(f"写到    : {path}")
        print(f"产物    : {len(lines)} 行（1 header + {len(lines) - 1} 条消息）")
        print("注意    : 本机无 OpenClaw，这一家只到 L1（我方读器往返），未做真机验收")
        return 0

    # ---- claude-code ----
    if args.dst in ("claude-code", "claude"):
        sid = str(uuid.uuid4())
        lines = mod.render(msgs, cwd, title=title, session_id=sid)
        path = mod.write(lines, args.out or os.path.expanduser("~/.claude"), sid, cwd=cwd)
        print(f"会话 id : {sid}")
        print(f"写到    : {path}")
        print(f"产物    : {len(lines)} 条消息")
        print("验收    : 用 Claude Code 的 /resume 看这条；或在装了 Claude 的机器上跑 selfcheck")
        return 0

    # ---- workbuddy ----
    if args.dst == "workbuddy":
        sid = str(uuid.uuid4())
        home = os.path.expanduser(args.install_wb_home) if args.install_wb_home else ""
        lines = mod.render(msgs, cwd, title=title, session_id=sid)
        base = home or os.path.expanduser(args.out)
        path = mod.write(lines, base, sid, project=args.project, cwd=cwd)
        print(f"会话 id : {sid}")
        print(f"写到    : {path}")
        if home:
            tpl = mod.register(path, sid, title, home=home, cwd=cwd)
            print(f"已登记  : sessions 表新增一行（模板取自会话 {str(tpl)[:8]}…）")
        else:
            print("未登记  : 只产了文件。要让产品看见，加 --install-wb-home <目录>")
        return 0

    # ---- codex：官方建壳、我们灌内容 ----
    if args.fill:
        if args.dst != "codex":
            ap.error("--fill 目前只对 codex 目标有效")
        home = args.install_codex_home or ""
        path, backup = mod.fill(msgs, args.fill, codex_home=home, title=title)
        print(f"灌入    : {path}")
        print(f"备份    : {backup}")
        print(f"投影归零: 已设为 (0,0)，产品会从第 0 字节重新解析")
        print("会话 id 未变，容器元数据（cwd/provider/账号/系统提示）未动。")
        return 0

    # ---- codex：自建容器 ----
    thread_id = str(uuid.uuid4())
    lines = mod.render(msgs, cwd, title=title, thread_id=thread_id)
    home = os.path.expanduser(args.install_codex_home) if args.install_codex_home else os.path.expanduser(args.out)
    path = mod.write(lines, home, thread_id)
    print(f"会话 id : {thread_id}")
    print(f"写到    : {path}")

    if args.install_codex_home:
        first_user = next((m.text for m in msgs if m.role == "user"), "")
        tpl = mod.register(path, thread_id, title,
                           codex_home=args.install_codex_home,
                           first_user_message=first_user)
        print(f"已登记  : threads 表新增一行（模板取自会话 {tpl[:8]}…）")
        print("现在它会出现在 codex 的会话列表里；点开/续跑由你验。")
    else:
        print("未登记  : 只产了文件。要让 codex 看见，加 --install-codex-home <CODEX_HOME>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
