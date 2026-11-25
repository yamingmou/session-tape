"""Qwen（QwenWorkCN 桌面端）引擎：读 / 写 `agents.db`。

实测基线：QwenWorkCN（`/Applications/QwenWorkCN.app`），库在
`~/Library/Application Support/QwenWorkCN/data/agents.db`，实测 11 会话 / 356 条消息。

## 结构

    chats(id, name, project_id NOT NULL, created_at, updated_at, worktree_path, chat_type, ext, …)
    sub_chats(id, chat_id NOT NULL, session_id, mode, messages, …)
    messages(id, message_id NOT NULL, chat_id, sub_chat_id, sequence, role,
             parts TEXT NOT NULL, metadata TEXT NOT NULL, searchable_text, …)

- 时间戳是**秒**（不是毫秒）—— 实测 `1793805524`。
- `parts` 是 JSON 数组：`[{"type":"text","text":…}, {"type":"tool-…", …}]`；
  读取只取 `text`、`link` 之类带 `text` 的块，`tool-*` / `error` 跳过。
- ⭐ **`searchable_text` 是搜索的承载点**：FTS 触发器直接把它塞进 `messages_fts`
  （`AFTER INSERT ... VALUES (NEW.searchable_text, …)`）。不填它，消息在界面上有、
  **但搜不到**——又一个"两个地方都要写、只写一处等于没写"。
- `chats.project_id` 为 NOT NULL，且指向 `projects` 表；写入沿用模板会话的 `project_id`，
  这样它会落在同一个项目下（自造 project 没有依据，实测 opencode 那边就是这样翻车的）。
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import string
import time

NAME = "qwen"

_ALPHABET = string.ascii_lowercase + string.digits


def find_db(home: str = "") -> str | None:
    cands = []
    if home:
        cands.append(os.path.join(os.path.expanduser(home), "agents.db"))
    cands += [
        os.path.expanduser("~/Library/Application Support/QwenWorkCN/data/agents.db"),
        os.path.expanduser("~/.qwenwork/data/agents.db"),
        os.path.expanduser("~/.config/qwenwork/data/agents.db"),
        os.path.expanduser("%LOCALAPPDATA%/QwenWorkCN/data/agents.db"),
    ]
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def _connect(db: str, readonly: bool = False) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db}?mode=ro" if readonly else db, uri=readonly)
    con.row_factory = sqlite3.Row
    return con


def _new_id(prefix: str = "mw") -> str:
    """产品 id 形态：`mw` + 14 位小写字母数字（实测 `mw29hqwj96fcd8fk`）。"""
    return prefix + "".join(random.choice(_ALPHABET) for _ in range(14))


def list_sessions(db: str, limit: int = 20) -> list[tuple[str, str, int]]:
    con = _connect(db, readonly=True)
    try:
        rows = con.execute(
            "select id, name, updated_at from chats "
            "where archived_at is null and deleted_at is null "
            "order by updated_at desc limit ?", (limit,)).fetchall()
        return [(r["id"], r["name"] or "", r["updated_at"] or 0) for r in rows]
    finally:
        con.close()


def _text_of(parts_json: str) -> str:
    try:
        parts = json.loads(parts_json or "[]")
    except Exception:
        return ""
    out = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        t = p.get("type") or ""
        if t.startswith("tool"):          # 工具块不搬（按本项目的取舍）
            continue
        if t == "error":                  # 报错块不是对话内容
            continue
        txt = p.get("text")
        if isinstance(txt, str) and txt.strip():
            out.append(txt)
    return "\n".join(out)


def read_msgs(db: str, chat_id: str):
    from ..model import Msg

    con = _connect(db, readonly=True)
    try:
        rows = con.execute(
            "select role, sequence, parts, created_at from messages "
            "where chat_id=? order by sequence", (chat_id,)).fetchall()
        out = []
        for r in rows:
            if r["role"] not in ("user", "assistant"):
                continue
            text = _text_of(r["parts"])
            if text.strip():
                out.append(Msg(r["role"], text, int(r["created_at"] or 0) * 1000))
        return out
    finally:
        con.close()


def _template(con, table: str, where: str = "") -> dict | None:
    sql = f"select * from {table} {where} order by rowid desc limit 1"
    row = con.execute(sql).fetchone()
    return dict(row) if row else None


def _insert(con, table: str, vals: dict) -> None:
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    use = [c for c in cols if c in vals]
    con.execute(f"insert into {table} ({','.join(use)}) values ({','.join('?' * len(use))})",
                [vals[c] for c in use])


def write_msgs(msgs, db: str, *, title: str = "", cwd: str = "") -> str:
    """把对话写成一个新会话（chats + sub_chats + messages），列默认值来自产品自己建的行。"""
    if not msgs:
        raise SystemExit("✗ 没有可搬的消息")

    now_s = int(time.time())
    first_s = int((msgs[0].ts_ms or now_s * 1000) / 1000)
    # prev 要比首条**小 1**：设成相等会让首条被"单调性修正"顶高一秒（实测踩过）
    stamps, prev = [], first_s - 1
    for m in msgs:
        ts = int((m.ts_ms or (prev + 1) * 1000) / 1000)
        if ts <= prev:
            ts = prev + 1
        stamps.append(ts)
        prev = ts

    chat_id = _new_id()
    sub_id = _new_id()

    con = _connect(db)
    try:
        con.execute("BEGIN")
        tpl = _template(con, "chats", "where archived_at is null and deleted_at is null")
        if tpl is None:
            raise SystemExit("✗ 目标库里没有现成会话可当模板——先用 Qwen 建一条")
        chat = dict(tpl)
        chat.update({
            "id": chat_id,
            "name": title or "（迁移）",
            "created_at": stamps[0], "updated_at": stamps[-1],
            "archived_at": None, "deleted_at": None,
            "source_chat_id": None, "pr_url": None, "pr_number": None,
        })
        if cwd:
            chat["worktree_path"] = cwd
            chat["output_directory"] = cwd
        _insert(con, "chats", chat)

        tsub = _template(con, "sub_chats", f"where chat_id='{tpl['id']}'")
        if tsub is None:
            raise SystemExit("✗ 模板会话没有 sub_chat，无法照抄列默认值")
        sub = dict(tsub)
        sub.update({
            "id": sub_id, "chat_id": chat_id,
            "name": title or "（迁移）",
            # 会话标识：产品用 uuid 形态，这里生成一个独立的
            "session_id": f"{random.getrandbits(32):08x}-{random.getrandbits(16):04x}-"
                          f"{random.getrandbits(16):04x}-{random.getrandbits(16):04x}-"
                          f"{random.getrandbits(48):012x}",
            "messages": "[]",
            "created_at": stamps[0], "updated_at": stamps[-1],
            "stream_id": None,
        })
        _insert(con, "sub_chats", sub)

        for seq, (m, ts) in enumerate(zip(msgs, stamps)):
            text = m.text
            _insert(con, "messages", {
                "id": _new_id(), "message_id": _new_id(),
                "chat_id": chat_id, "sub_chat_id": sub_id,
                "sequence": seq, "role": m.role,
                "parts": json.dumps([{"type": "text", "text": text}], ensure_ascii=False),
                "metadata": json.dumps({"source": "session-tape"}, ensure_ascii=False),
                # ⭐ FTS 触发器只认这一列：不填 = 消息可见但搜不到
                "searchable_text": text,
                "search_status": "ready",
                "created_at": ts, "updated_at": ts,
            })
        con.commit()
        return chat_id
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
