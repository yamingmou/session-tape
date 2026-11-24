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
    """把对话写进库：**旧新一代都补**，列默认值来自产品自己建的一行（模板行策略）。

    ⚠️ **实测未通过（2026-11-24）**：两代都补上之后，我方读器能读回，
    但产品自己的 `opencode session list` **列不出来**——它靠 project 映射，
    而我们复制的是模板会话的 project_id。这正是"文件在、产品看不见"。

    ⇒ 因此本函数只算"写进了库"，**不算落地**。CLI 会在之后用产品自己的
    `session list` 再验一次，列不出来就报未通过（返回码 2）。
    正路应是官方 `session import`，但实测对新会话返回 `Bad Request`（已试：换 id /
    不给 id / 去 projectID / 加 --standalone），格式尚未攻克。**不猜，留作待办。**
    """
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

# ---------------------------------------------------------------- 官方通道

def find_cli() -> str | None:
    """找可调用的 opencode 可执行文件（PATH 优先，其次桌面客户端里带的那个）。

    桌面客户端（OpenCode.app）会把 CLI 一起打包：
    `Contents/Resources/opencode-cli` —— 有它就能走**官方 import/export**，
    不必手搓库表（手搓过的后果见下方 `import_via_cli` 的说明）。
    """
    import shutil
    for name in ("opencode", "opencode-cli"):
        p = shutil.which(name)
        if p:
            return p
    for cand in ("/Applications/OpenCode.app/Contents/Resources/opencode-cli",
                 os.path.expanduser("~/Applications/OpenCode.app/Contents/Resources/opencode-cli")):
        if os.path.exists(cand):
            return cand
    return None


def build_import(msgs, *, title: str, cwd: str, session_id: str | None = None) -> dict:
    """造 `session import` 能吃的 JSON（形状照 `session export` 抄）。"""
    sid = session_id or _new_session_id()
    stamps, prev = [], int(msgs[0].ts_ms or time.time() * 1000)
    for m in msgs:
        ts = int(m.ts_ms or (prev + 1000))
        if ts <= prev:
            ts = prev + 1000
        stamps.append(ts)
        prev = ts
    return {
        "info": {
            "id": sid,
            "title": title or "（迁移）",
            "time": {"created": stamps[0], "updated": stamps[-1]},
            "location": {"directory": cwd},
            "cost": 0,
            "tokens": {"input": 0, "output": 0, "reasoning": 0,
                       "cache": {"read": 0, "write": 0}},
        },
        "messages": [
            {"id": f"msg_import{i:08d}", "time": {"created": ts},
             "type": m.role, "text": m.text}
            for i, (m, ts) in enumerate(zip(msgs, stamps))
        ],
    }


def import_via_cli(msgs, *, title: str, cwd: str, cli: str | None = None) -> tuple[str, str]:
    """走**官方通道**：写 JSON → `opencode session import` → 用 `session list` 自证。

    为什么不用手搓库表：实测过——手写 `session`/`message`/`part` + `session_v2`/`session_message`
    两代都补上，`opencode session list` 仍然**列不出来**（它靠 project 映射，
    而我们复制的是模板会话的 project_id）。这正是"文件在、产品看不见"。
    官方 import 会自己建投影与映射，然后**产品自己就能列出来**——这才是可验证的落地。
    """
    import json as _json
    import subprocess
    import tempfile

    cli = cli or find_cli()
    if not cli:
        raise SystemExit("✗ 找不到 opencode 可执行文件（PATH 里没有，桌面客户端也没找到）")

    doc = build_import(msgs, title=title, cwd=cwd)
    tmp = tempfile.mkdtemp(prefix="oc-import-")
    path = os.path.join(tmp, "session.json")
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(doc, f, ensure_ascii=False)

    r = subprocess.run([cli, "session", "import", path, "--directory", cwd],
                       capture_output=True, text=True, encoding="utf-8", timeout=180)
    if r.returncode != 0:
        raise SystemExit(f"✗ import 失败：{(r.stdout + r.stderr)[-400:]}")
    return doc["info"]["id"], (r.stdout or "").strip()


def listed_by_product(session_id: str, cwd: str, cli: str | None = None) -> bool:
    """**产品自己**能不能列出这条会话（在它自己的目录里跑 `session list`）。"""
    import subprocess
    cli = cli or find_cli()
    if not cli:
        return False
    r = subprocess.run([cli, "session", "list"], cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", timeout=120)
    return session_id in (r.stdout or "")

# ---------------------------------------------------------------- v2 写入（照真机基准）

def find_project(db: str, directory: str) -> str | None:
    """查目录对应的 `project_id`；没有就返回 None。

    ⚠️ **不能自己造这个 id**（实测：13 个已知 project 行，sha1/sha256/blake2b/md5
    各种变体 0 命中 ⇒ 不是简单哈希，是产品创建时生成的随机 id）。
    而且 `project` 行**只有产品自己会建**：用户在客户端里打开某个目录/在那里新建会话时生成。
    实测过三种"借产品的手"的办法，都不行：
      · 在目录里跑 `session list` → 不建；
      · 用真实 export 原样 import → 回 `Session already exists`，在建 project 之前就短路；
      · 用改过 id 的 export import → 回 `Bad Request` / `Internal Server Error`，也没建。
    ⇒ 所以这里只查不造，查不到就**明说有哪些目录可用**，让人去客户端里开一次。
    """
    from pathlib import Path

    real = str(Path(directory).resolve())
    con = _connect(db, readonly=True)
    try:
        for cand in (real, str(directory), str(directory).rstrip("/")):
            row = con.execute("select id from project where worktree=?", (cand,)).fetchone()
            if row:
                return row["id"]
        return None
    finally:
        con.close()


def known_directories(db: str) -> list[str]:
    """客户端已经认可的目录（有 project 行的）——迁不过去时列给人看。"""
    con = _connect(db, readonly=True)
    try:
        return [r["worktree"] for r in
                con.execute("select worktree from project where id!='global' order by time_active desc")
                if r["worktree"] and r["worktree"] != "/"]
    finally:
        con.close()


def write_v2(msgs, db: str, *, title: str = "", cwd: str = "",
             session_id: str | None = None, cli: str | None = None) -> str:
    """只写**新一代** `session_v2` + `session_message`（形状照真机基准 `测试输出1` 抄）。

    与旧实现的差别（都是实测出来的）：
      · `session` 表**不写**——新版客户端只写 v2（基准那条会话在 `session` 里 0 行）；
      · 必须有 `project` 行，否则产品列不出来（`session list` 按目录→项目过滤）；
      · user 消息的 data 不是 `{"text":…}`，而是带 `metadata.displayText/agent/model` 的完整结构；
      · assistant 的 data 带 `time.streamed/completed`、`finish`、`tokens`；
      · 末尾要一条 `idle` 消息（`{"time":{"created":…},"outcome":"succeeded"}`）。
    """
    sid = session_id or _new_session_id()
    now_ms = int(time.time() * 1000)
    stamps, prev = [], int(msgs[0].ts_ms or now_ms)
    for m in msgs:
        ts = int(m.ts_ms or (prev + 1000))
        if ts <= prev:
            ts = prev + 1000
        stamps.append(ts)
        prev = ts

    pid = find_project(db, cwd)
    if not pid:
        dirs = known_directories(db)
        raise SystemExit(
            "✗ 这个目录在客户端里还没有出现过，产品不会列出这条会话。\n"
            f"  目录：{cwd}\n"
            "  办法：在 OpenCode 客户端里打开这个目录（或在那里新建一次会话），再重试。\n"
            "  客户端已认可的目录：\n" + "\n".join(f"    · {d}" for d in dirs[:10]))

    con = _connect(db)
    try:
        con.execute("BEGIN")
        tpl = con.execute("select * from session_v2 order by time_updated desc limit 1").fetchone()
        if tpl is None:
            raise SystemExit("✗ 目标库里没有 session_v2 行可当模板——先用产品建一条")
        row = dict(tpl)
        row.update({
            "id": sid, "project_id": pid, "directory": cwd,
            "title": title or "（迁移）",
            "parent_id": None, "fork_session_id": None, "fork_boundary": None,
            "time_created": stamps[0], "time_updated": stamps[-1],
            "time_busy": stamps[0], "time_idle": stamps[-1], "time_viewed": stamps[-1],
            "idle_outcome": "succeeded",
            "cost": 0,
            "tokens_input": 0, "tokens_output": 0, "tokens_reasoning": 0,
            "tokens_cache_read": 0, "tokens_cache_write": 0,
        })
        row.setdefault("slug", "migrated-session")
        _insert(con, "session_v2", row)

        model = {"id": "migrated", "providerID": "migrated", "variant": "default"}
        seq = 1
        for m, ts in zip(msgs, stamps):
            if m.role == "user":
                data = {"metadata": {"displayText": m.text[:80], "comments": [], "attachments": [],
                                     "agent": "build",
                                     "model": {"modelID": "migrated", "providerID": "migrated"}},
                        "time": {"created": ts}, "text": m.text, "files": [], "agents": []}
            else:
                data = {"time": {"created": ts, "streamed": ts, "completed": ts},
                        "agent": "build", "model": model,
                        "content": [{"type": "text", "text": m.text}],
                        "finish": "stop", "rawFinish": "stop", "cost": 0,
                        "tokens": {"input": 0, "output": 0, "reasoning": 0,
                                   "cache": {"read": 0, "write": 0}}}
            _insert(con, "session_message", {
                "id": f"msg_{sid[4:14]}{seq:04d}", "session_id": sid,
                "type": m.role, "seq": seq,
                "time_created": ts, "time_updated": ts,
                "data": json.dumps(data, ensure_ascii=False),
            })
            seq += 1
        _insert(con, "session_message", {
            "id": f"msg_{sid[4:14]}{seq:04d}", "session_id": sid,
            "type": "idle", "seq": seq,
            "time_created": stamps[-1], "time_updated": stamps[-1],
            "data": json.dumps({"time": {"created": stamps[-1]}, "outcome": "succeeded"}),
        })
        con.commit()
        return sid
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
