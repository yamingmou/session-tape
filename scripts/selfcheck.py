#!/usr/bin/env python3
"""自检：一条命令跑完"能不能用"，并打印一张过/不过的表。

它不装任何产品、不碰用户数据：全部在临时目录里做**往返测试**
（渲染 → 落盘 → 用产品口径读回 → 比对）。产品在场时（pi / codex）再加一层真机门禁。

用法:
  python3 scripts/selfcheck.py                 # 只做不需要产品的检查
  python3 scripts/selfcheck.py --pi <pi可执行>  # 再加 pi 的真机门禁
退出码 0 = 全过。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from session_tape import noise                      # noqa: E402
from session_tape.model import Msg                  # noqa: E402
from session_tape.render import codex, pi, workbuddy  # noqa: E402

ROWS: list[tuple[str, bool, str]] = []


def check(name: str, fn):
    try:
        detail = fn() or ""
        ROWS.append((name, True, detail))
    except Exception as e:
        ROWS.append((name, False, f"{type(e).__name__}: {e}"))


def _msgs():
    # 文本故意写长：pi 门禁要用"≥12 字的历史标记"来判断内容是否真进了上下文
    return [Msg("user", "第一问：这是一个足够长的提问用来当标记", 1_700_000_000_000),
            Msg("assistant", "第一答：这是足够长的回答内容也当标记", 1_700_000_001_000),
            Msg("user", "第二问：再来一个足够长的提问", 0),
            Msg("assistant", "第二答：再来一个足够长的回答", 0)]


# ---------------- 契约测试（四个文件） ----------------
def t_tests():
    out = []
    for f in sorted(os.listdir(os.path.join(ROOT, "tests"))):
        if not (f.startswith("test_") and f.endswith(".py")):
            continue
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", f)],
                           capture_output=True, text=True, encoding="utf-8")
        out.append(f"{f}{'✓' if r.returncode == 0 else '✗'}")
        if r.returncode:
            raise AssertionError(f"{f} 未过：{(r.stdout or r.stderr)[-300:]}")
    return " ".join(out)


# ---------------- 三目标的往返测试 ----------------
def t_pi_roundtrip():
    tmp = tempfile.mkdtemp(prefix="selfcheck-pi-")
    sess = os.path.join(tmp, "sessions", "--tmp--")
    os.makedirs(sess, exist_ok=True)
    text = pi.render(_msgs(), "/tmp/proj")
    path = os.path.join(sess, "s.jsonl")
    open(path, "w", encoding="utf-8").write(text)
    from fork_core import adapters
    ad = adapters.get_adapter("pi")
    rows = ad.read_lines(path)
    got = [ad.get_text(o) for o in rows if ad.is_user_message(o) or ad.is_assistant_message(o)]
    assert [g[:3] for g in got] == ["第一问", "第一答", "第二问", "第二答"], got
    return f"{len(got)} 条往返一致"


def t_codex_roundtrip():
    tmp = tempfile.mkdtemp(prefix="selfcheck-codex-")
    lines = codex.render(_msgs(), "/tmp/proj", thread_id="11111111-2222-3333-4444-555555555555")
    path = codex.write(lines, tmp, "11111111-2222-3333-4444-555555555555")
    from fork_core.adapter_codex import CodexAdapter
    ad = CodexAdapter()
    rows = ad.read_lines(path)
    got = [ad.get_text(o) for o in rows if ad.is_user_message(o) or ad.is_assistant_message(o)]
    assert [g[:3] for g in got] == ["第一问", "第一答", "第二问", "第二答"], got
    return f"{len(got)} 条往返一致；落盘 {os.path.basename(path)[:28]}…"


def t_workbuddy_roundtrip():
    tmp = tempfile.mkdtemp(prefix="selfcheck-wb-")
    lines = workbuddy.render(_msgs(), "/tmp/proj", session_id="22222222-3333-4444-5555-666666666666")
    path = workbuddy.write(lines, tmp, "22222222-3333-4444-5555-666666666666", cwd="/tmp/proj")
    import fork_core.adapter_workbuddy as wbmod
    prev = (wbmod.DB_PATH, wbmod.PROJECTS_DIR)
    wbmod.DB_PATH = os.path.join(tmp, "none.db")
    wbmod.PROJECTS_DIR = os.path.join(tmp, "projects")
    try:
        ad = wbmod.WorkBuddyAdapter()
        rows = ad.read_lines(path)
        got = [ad.get_text(o) for o in rows if ad.is_user_message(o) or ad.is_assistant_message(o)]
    finally:
        wbmod.DB_PATH, wbmod.PROJECTS_DIR = prev
    assert [g[:3] for g in got] == ["第一问", "第一答", "第二问", "第二答"], got
    return f"{len(got)} 条往返一致；项目目录 {os.path.basename(os.path.dirname(path))}"


def t_noise():
    stats = {}
    out = noise.clean([Msg("user", "<user_query>真问题</user_query>", 1),
                       Msg("assistant", "Interrupted by user", 2),
                       Msg("user", "真问题", 3)], stats)
    # 占位被丢掉后，两条同文变成相邻 ⇒ **合并成一条**（这是刻意的）
    assert [m.text for m in out] == ["真问题"], [m.text for m in out]
    assert "占位/中断文本" in stats and "重复投递（相邻同文）" in stats, stats
    return f"丢 {stats}"


def t_chain():
    """链式：WorkBuddy 渲染 → 用 pi 读法读回 → 再用 codex 渲染。"""
    wb_lines = workbuddy.render(_msgs(), "/tmp/proj", session_id="33333333-4444-5555-6666-777777777777")
    tmp = tempfile.mkdtemp(prefix="selfcheck-chain-")
    wbpath = workbuddy.write(wb_lines, tmp, "33333333-4444-5555-6666-777777777777", cwd="/tmp/proj")
    import fork_core.adapter_workbuddy as wbmod
    prev = (wbmod.DB_PATH, wbmod.PROJECTS_DIR)
    wbmod.DB_PATH = os.path.join(tmp, "none.db"); wbmod.PROJECTS_DIR = os.path.join(tmp, "projects")
    try:
        ad = wbmod.WorkBuddyAdapter()
        rows = ad.read_lines(wbpath)
        mid = [Msg("user" if ad.is_user_message(o) else "assistant", ad.get_text(o))
               for o in rows if ad.is_user_message(o) or ad.is_assistant_message(o)]
    finally:
        wbmod.DB_PATH, wbmod.PROJECTS_DIR = prev
    lines = codex.render(mid, "/tmp/proj", thread_id="44444444-5555-6666-7777-888888888888")
    from fork_core.adapter_codex import CodexAdapter
    ca = CodexAdapter()
    path = codex.write(lines, os.path.join(tmp, "codex"), "44444444-5555-6666-7777-888888888888")
    out = [ca.get_text(o) for o in ca.read_lines(path) if ca.is_user_message(o) or ca.is_assistant_message(o)]
    assert [o[:3] for o in out] == ["第一问", "第一答", "第二问", "第二答"], out
    return "WB → 读回 → codex，4 条一致"


def t_pi_gate(pi_bin: str):
    tmp = tempfile.mkdtemp(prefix="selfcheck-gate-")
    sess = os.path.join(tmp, "sessions", "--tmp--")
    os.makedirs(sess, exist_ok=True)
    path = os.path.join(sess, "s.jsonl")
    open(path, "w", encoding="utf-8").write(pi.render(_msgs(), "/tmp/proj"))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "verify_gate_pi.py"),
                        "--pi", pi_bin, "--session", path],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise AssertionError((r.stdout or r.stderr)[-400:])
    return "门禁四条断言全过"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi", help="pi 可执行文件（给了就跑真机门禁）")
    args = ap.parse_args()

    check("契约测试（4 份）", t_tests)
    check("噪声过滤", t_noise)
    check("pi 往返", t_pi_roundtrip)
    check("codex 往返", t_codex_roundtrip)
    check("workbuddy 往返", t_workbuddy_roundtrip)
    check("链式 WB→读回→codex", t_chain)
    if args.pi:
        check("pi 真机门禁", lambda: t_pi_gate(args.pi))

    w = max(len(n) for n, _, _ in ROWS)
    print(f"\n{'检查项'.ljust(w)}  结果  说明")
    print("-" * (w + 40))
    for name, ok, detail in ROWS:
        print(f"{name.ljust(w)}  {'✅' if ok else '❌'}    {detail[:70]}")
    bad = [n for n, ok, _ in ROWS if not ok]
    print()
    if bad:
        print(f"✗ {len(bad)} 项未过：{', '.join(bad)}")
        return 1
    print(f"✅ 全部 {len(ROWS)} 项通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
