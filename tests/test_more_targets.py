#!/usr/bin/env python3
"""claude-code / hermes / openclaw 三个目标的往返测试。

**验收等级不同，这里如实分开写**：
  · claude-code：本机没装产品 ⇒ **L1**（我方读器往返；行形状取自适配器真机夹具）
  · hermes：本机有真样本库（一份 10 会话的真机样本库）⇒ **L2**（写进库副本 + 读回）
  · openclaw：本机没装产品 ⇒ **L1**（同形校验：它旧版读取器**直接继承 pi 的**，代码级）
"""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FORK = os.environ.get("FORK_CORE_PATH")
if FORK and FORK not in sys.path:
    sys.path.insert(0, FORK)

from session_tape.model import Msg          # noqa: E402
from session_tape.render import claude, hermes, openclaw   # noqa: E402

MSGS = [Msg("user", "第一问：这是一个足够长的提问", 1_700_000_000_000),
        Msg("assistant", "第一答：足够长的回答内容", 1_700_000_001_000)]

try:
    import fork_core  # noqa: F401
    HAS_FORK = True
except Exception:
    HAS_FORK = False


def t_claude():
    """L1：树状结构（parentUuid 串链）+ 按 cwd 转义的目录。"""
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    lines = claude.render(MSGS, "/Users/a/proj", session_id=sid)
    assert len(lines) == 2
    assert lines[0]["type"] == "user" and lines[0]["parentUuid"] is None
    assert lines[1]["parentUuid"] == lines[0]["uuid"], "parentUuid 必须串链"
    assert all(o["sessionId"] == sid and o["cwd"] == "/Users/a/proj" for o in lines)
    assert lines[0]["message"]["content"][0]["type"] == "text"
    tmp = tempfile.mkdtemp(prefix="claude-")
    path = claude.write(lines, tmp, sid, cwd="/Users/a/proj")
    assert path.endswith(os.path.join("projects", "-Users-a-proj", sid + ".jsonl")), path
    if not HAS_FORK:
        return "L1：结构与路径 OK（未装 session-fork-core，跳过读回）"
    import fork_core.adapter_claude_code as cm
    prev = os.environ.get("CLAUDE_DIR")
    os.environ["CLAUDE_DIR"] = tmp
    try:
        ad = cm.ClaudeCodeAdapter()
        got = [ad.get_text(o) for o in ad.read_lines(path)
               if ad.is_user_message(o) or ad.is_assistant_message(o)]
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_DIR", None)
        else:
            os.environ["CLAUDE_DIR"] = prev
    assert [g[:3] for g in got] == ["第一问", "第一答"], got
    return "L1：树链 + 目录 + 读回 2 条一致"


def t_hermes():
    """L2：写进真样本库的**副本**，再用 SQLite 读回。"""
    # 样本库路径由环境变量给（默认取产品的家目录）；没有样本就跳过，不写死任何机器路径
    src = os.path.expanduser(os.environ.get("HERMES_SAMPLE_DB", "~/.hermes/state.db"))
    if not (HAS_FORK and os.path.exists(src)):
        return "跳过（需要 session-fork-core + 一个 Hermes 样本库：HERMES_SAMPLE_DB）"
    tmp = tempfile.mkdtemp(prefix="hermes-")
    db = os.path.join(tmp, "state.db")
    shutil.copy(src, db)
    sid = "20261124_000000_tapez"
    rows = hermes.render(MSGS, sid)
    assert all(isinstance(r["timestamp"], float) for r in rows), "Hermes 时间戳是秒的浮点"
    hermes.write(rows, db, sid)
    con = sqlite3.connect(db)
    n = con.execute("select count(*) from messages where session_id=?", (sid,)).fetchone()[0]
    roles = [r[0] for r in con.execute("select role from messages where session_id=? order by id", (sid,))]
    assert n == 2 and roles == ["user", "assistant"], (n, roles)
    return "L2：会话行 + 2 条消息写入并读回"


def t_openclaw():
    """L1：与 pi 同形（旧版读取器直接继承 PiAdapter）——用它的读器验。"""
    sid = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
    lines = openclaw.render(MSGS, "/tmp/proj", session_id=sid)
    assert lines[0]["type"] == "session" and lines[0]["id"] == sid
    assert lines[1]["message"]["role"] == "user"
    tmp = tempfile.mkdtemp(prefix="oc-")
    path = openclaw.write(lines, tmp, sid)
    assert path.endswith(os.path.join("agents", "main", "sessions", sid + ".jsonl")), path
    if not HAS_FORK:
        return "L1：结构与路径 OK（未装 session-fork-core，跳过读回）"
    from fork_core.adapter_openclaw import OpenClawJsonlAdapter
    ad = OpenClawJsonlAdapter()
    got = [ad.get_text(o) for o in ad.read_lines(path)
           if ad.is_user_message(o) or ad.is_assistant_message(o)]
    assert [g[:3] for g in got] == ["第一问", "第一答"], got
    return "L1：同形 + 读回 2 条一致"


print("claude-code :", t_claude())
print("hermes      :", t_hermes())
print("openclaw    :", t_openclaw())
print("\n✅ 三目标测试通过")
