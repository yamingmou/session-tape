"""目标：Hermes（`~/.hermes/state.db` 的 `sessions` + `messages` 两张表）。

与前面三个目标的本质差别：**没有"文件"**，会话就是库里的一行 + 若干消息行。
所以这里只产**消息行**（`messages` 表那一行一行），落库与登记交给适配器
（它已经有事务化的 `finalize_branch`，那是真机验过的）。

行形状取自**真机样本**（一个 10 会话 / 35 消息的 Hermes 库）：
  `messages(session_id, role, content, timestamp REAL 秒, active, observed, compacted, ...)`
  —— 26 列里我们只填必要的，其余留空（产品用默认值）。
"""
from __future__ import annotations

import os


def render(msgs, session_id: str, *, start_ts: float | None = None) -> list[dict]:
    """产 `messages` 行（`timestamp` 是 **Unix 秒的浮点数**，不是毫秒、不是 ISO）。"""
    if not msgs:
        raise SystemExit("✗ 没有可搬的消息（源里全是占位/工具内容？）")

    import time
    base = (msgs[0].ts_ms / 1000) if msgs[0].ts_ms else (start_ts or time.time())
    rows, prev = [], base
    for m in msgs:
        ts = (m.ts_ms / 1000) if m.ts_ms else prev + 1.0
        if ts <= prev:
            ts = prev + 1.0
        rows.append({
            "session_id": session_id,
            "role": m.role,
            "content": m.text,
            "timestamp": float(ts),
            "active": 1,
            "observed": 0,
            "compacted": 0,
            "_compressed_summary": 0,
            "token_count": None,
            "finish_reason": None,
            "tool_call_id": None,
            "tool_calls": None,
            "tool_name": None,
            "reasoning": None,
        })
        prev = ts
    return rows


def write(rows: list[dict], db_path: str, session_id: str, *, template_id: str | None = None) -> str:
    """把消息行写进库：走适配器的 `branch_target → write_branch → finalize_branch`。

    这三步是适配器给"打分支"用的正式链路（一个事务写完 `sessions` + `messages`），
    迁移直接复用——**不自己拼 INSERT**，避免漏掉 NOT NULL 列或触发器。

    ⚠️ Hermes 适配器在 `__init__` 里读 `HERMES_HOME` ⇒ 必须**先设环境变量再构造**，
    否则会写到默认的 `~/.hermes`（与 codex 的 `CODEX_HOME` 同一个坑）。
    """
    try:
        from .._deps import ensure_fork_core
        ensure_fork_core()
        from fork_core.adapter_hermes import HermesAdapter, make_ref   # type: ignore
        from fork_core.models import SessionMeta                       # type: ignore
    except Exception as e:                                             # pragma: no cover
        raise SystemExit(f"✗ 需要 session-fork-core：{e}")

    db = os.path.abspath(os.path.expanduser(db_path))
    if not os.path.exists(db):
        raise SystemExit(f"✗ 库里不存在：{db}")

    prev_home = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = os.path.dirname(db)
    try:
        ad = HermesAdapter()
        tpl = template_id or _first_session_id(ad)
        if not tpl:
            raise SystemExit("✗ 目标库里没有现成会话可当模板——先用 Hermes 跑一轮")

        src_ref = make_ref(ad.DB_PATH, tpl)
        dst_ref = ad.branch_target(src_ref, session_id)     # 版本闸在这里 fail-fast
        tmp_ref = f"tape:{session_id}"
        ad.write_branch(tmp_ref, rows)
        ad.finalize_branch(tmp_ref, dst_ref)
        ad.register_branch(SessionMeta(id=tpl, title=""), session_id, dst_ref, "（迁移）",
                           parent_id=tpl)
        return dst_ref
    finally:
        if prev_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = prev_home


def _first_session_id(ad) -> str:
    try:
        con = ad._connect(readonly=True)
        try:
            row = con.execute("select id from sessions order by rowid desc limit 1").fetchone()
            return row[0] if row else ""
        finally:
            con.close()
    except Exception:
        return ""
