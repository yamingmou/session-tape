"""OpenCode 引擎：读 / 写 `opencode.db`。

**为什么单独一个模块而不是复用适配器层**：`session-fork-core` 只覆盖我们已有的六个产品，
OpenCode 在它之外。新引擎进来时，读取与写入都归本仓库自己维护——这也正是"任意平台互迁"
要付出的真实成本：**每加一个产品 = 读器 + 写器 + 契约测试**。

实测基线：OpenCode **1.14.28**，`~/.local/share/opencode/opencode.db`（23 MB，18 会话）。

## ⚠️ 这个库有两代存储，而且同一批会话可能只有其中一代

| 代 | 表 | 观察 |
|---|---|---|
| 旧 | `session` / `message`（`data.role`）/ `part`（`data.type`） | 有的会话只有这一代 |
| 新 | `session_v2` / `session_message`（`type` + `seq`，`data` 扁平） | 有的会话两代都有；新会话可能只有这一代 |

⇒ **只写一代就是押注产品认哪一代**。所以写入时**两代都补**（多写不会有副作用，
少写则可能"文件在、产品看不见"——那是我们踩过的坑）。

## 数据形状（照真机样本抄）

- 旧 `message.data`：`{"role":"user","time":{"created":ms},"agent":…,"model":…,"summary":{"diffs":[]}}`
- 旧 `part.data`：`{"type":"text","text":"…"}`，挂 `message_id` + `session_id`
- 新 `session_message`(user)：`data = {"text":"…"}`、`type="user"`、`seq` 自增
- 新 `session_message`(assistant)：`data = {"agent":…,"model":{…},"content":[{"type":"text","text":…}]}`
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import string
import time

NAME = "opencode"

_ALPHABET = string.ascii_letters + string.digits


def find_db(home: str = "") -> str | None:
    """按产品的探测顺序找库；都找不到返回 None（不是错误）。"""
    cands = []
    if home:
        cands.append(os.path.join(os.path.expanduser(home), "opencode.db"))
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        cands.append(os.path.join(xdg, "opencode", "opencode.db"))
    cands += [
        os.path.expanduser("~/.local/share/opencode/opencode.db"),
        os.path.expanduser("~/Library/Application Support/opencode/opencode.db"),
    ]
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def _connect(db: str, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _has_table(con, name: str) -> bool:
    return con.execute("select 1 from sqlite_master where type='table' and name=?",
                       (name,)).fetchone() is not None


def _new_session_id() -> str:
    return "ses_" + "".join(random.choice(_ALPHABET) for _ in range(24))


def list_sessions(db: str, limit: int = 20) -> list[tuple[str, str, int]]:
    """[(id, title, time_updated)]，最近的在前。"""
    con = _connect(db, readonly=True)
    try:
        rows = con.execute(
            "select id, title, time_updated from session order by time_updated desc limit ?",
            (limit,)).fetchall()
        return [(r["id"], r["title"] or "", r["time_updated"] or 0) for r in rows]
    finally:
        con.close()


def read_msgs(db: str, session_id: str):
    """读一条会话的对话（只取 user / assistant 的正文）。"""
    from ..model import Msg

    con = _connect(db, readonly=True)
    try:
        out: list[Msg] = []

        # 新一代优先：session_message（扁平，type + seq）
        if _has_table(con, "session_message"):
            rows = con.execute(
                "select type, seq, time_created, data from session_message "
                "where session_id=? and type in ('user','assistant') order by seq",
                (session_id,)).fetchall()
            for r in rows:
                data = json.loads(r["data"] or "{}")
                if r["type"] == "user":
                    text = data.get("text") or ""
                else:
                    text = "".join(b.get("text", "") for b in (data.get("content") or [])
                                   if isinstance(b, dict) and b.get("type") in ("text", "output_text"))
                if text.strip():
                    out.append(Msg("user" if r["type"] == "user" else "assistant",
                                   text, int(r["time_created"] or 0)))
            if out:
                return out

        # 旧一代：message(role) ⋈ part(text)
        if _has_table(con, "message"):
            rows = con.execute(
                "select m.id as mid, json_extract(m.data,'$.role') as role, "
                "       m.time_created as tc "
                "from message m where m.session_id=? order by m.time_created", (session_id,)).fetchall()
            for r in rows:
                role = r["role"]
                if role not in ("user", "assistant"):
                    continue
                parts = con.execute(
                    "select data from part where message_id=? order by time_created", (r["mid"],)).fetchall()
                text = "".join(json.loads(p["data"] or "{}").get("text", "")
                               for p in parts
                               if json.loads(p["data"] or "{}").get("type") in ("text", "input_text", "output_text"))
                if text.strip():
                    out.append(Msg(role, text, int(r["tc"] or 0)))
        return out
    finally:
        con.close()


def _template_row(con, table: str) -> dict | None:
    if not _has_table(con, table):
        return None
    row = con.execute(f"select * from {table} order by rowid desc limit 1").fetchone()
    return dict(row) if row else None


def _insert(con, table: str, vals: dict) -> None:
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    use = [c for c in cols if c in vals]
    con.execute(f"insert into {table} ({','.join(use)}) values ({','.join('?' * len(use))})",
                [vals[c] for c in use])


def write_msgs(msgs, db: str, *, title: str = "", cwd: str = "",
               session_id: str | None = None) -> str:
    """把对话写进库：**旧新一代都补**，列默认值来自产品自己建的一行（模板行策略）。"""
    if not msgs:
        raise SystemExit("✗ 没有可搬的消息（源里全是占位/工具内容？）")

    sid = session_id or _new_session_id()
    now_ms = int(time.time() * 1000)
    stamps, prev = [], int(msgs[0].ts_ms or now_ms)
    for m in msgs:
        ts = int(m.ts_ms or (prev + 1000))
        if ts <= prev:
            ts = prev + 1000
        stamps.append(ts)
        prev = ts

    con = _connect(db)
    try:
        con.execute("BEGIN")

        # ---- 旧一代：session / message / part ----
        tpl = _template_row(con, "session")
        if tpl is None:
            raise SystemExit("✗ 目标库里没有现成会话可当模板——先用 OpenCode 建一条")
        row = dict(tpl)
        row.update({
            "id": sid, "title": title or row.get("title") or "（迁移）",
            "directory": cwd or row.get("directory") or os.path.expanduser("~"),
            "parent_id": None,
            "time_created": stamps[0], "time_updated": stamps[-1],
        })
        for k in ("cost", "tokens_input", "tokens_output", "tokens_reasoning",
                  "tokens_cache_read", "tokens_cache_write"):
            if k in row:
                row[k] = 0
        _insert(con, "session", row)

        for i, (m, ts) in enumerate(zip(msgs, stamps), 1):
            mid = f"msg_{sid[4:14]}{i:04d}"
            _insert(con, "message", {
                "id": mid, "session_id": sid,
                "time_created": ts, "time_updated": ts,
                "data": json.dumps({"role": m.role, "time": {"created": ts},
                                    "summary": {"diffs": []}}, ensure_ascii=False),
            })
            _insert(con, "part", {
                "id": f"prt_{sid[4:14]}{i:04d}", "message_id": mid, "session_id": sid,
                "time_created": ts, "time_updated": ts,
                "data": json.dumps({"type": "text", "text": m.text}, ensure_ascii=False),
            })

        # ---- 新一代：session_v2 / session_message ----
        tpl2 = _template_row(con, "session_v2")
        if tpl2 is not None:
            row2 = dict(tpl2)
            row2.update({
                "id": sid, "title": title or row2.get("title") or "（迁移）",
                "directory": cwd or row2.get("directory") or os.path.expanduser("~"),
                "parent_id": None, "fork_session_id": None, "fork_boundary": None,
                "time_created": stamps[0], "time_updated": stamps[-1],
            })
            for k in ("cost", "tokens_input", "tokens_output", "tokens_reasoning",
                      "tokens_cache_read", "tokens_cache_write"):
                if k in row2:
                    row2[k] = 0
            _insert(con, "session_v2", row2)

            if _has_table(con, "session_message"):
                for i, (m, ts) in enumerate(zip(msgs, stamps)):
                    if m.role == "user":
                        data = {"text": m.text}
                    else:
                        data = {"agent": "build", "model": {}, "content": [{"type": "text", "text": m.text}]}
                    _insert(con, "session_message", {
                        "id": f"msg_{sid[4:14]}v2{i:04d}", "session_id": sid,
                        "type": m.role, "seq": i,
                        "time_created": ts, "time_updated": ts,
                        "data": json.dumps(data, ensure_ascii=False),
                    })

        con.commit()
        return sid
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
