"""目标：WorkBuddy（`~/.workbuddy/workbuddy.db` + `projects/<项目>/<会话>.jsonl`）。

和 codex 一样是**两件套**：
  ① 转录文件 —— `projects/<项目目录>/<会话id>.jsonl`，逐行
     `{id, parentId, timestamp(ms), type:"message", role, content:[{type,text}]}`；
  ② `sessions` 表一行 —— 产品靠它把会话列出来（含项目归属、标题、状态、时间）。

我们**不发明**写入规则：转录用适配器的 `write_branch`（它已处理转义与编码），
登记用 `register_branch`（复制一条产品自己建的记录当模板，只换 id/标题/时间）。

⚠️ 隔离要 patch **模块级常量**：适配器的 `_connect()` 用的是模块级 `DB_PATH`，
只改实例属性不生效（这是读源码确认的，不是猜）。
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime


def _iso_ms(ms: int) -> int:
    return int(ms)


def render(msgs, cwd: str, *, title: str = "", session_id: str | None = None,
           model: str = "migrated") -> list[dict]:
    """渲染成 WorkBuddy 转录的行序列（id 链 + 毫秒时间戳）。"""
    if not msgs:
        raise SystemExit("✗ 没有可搬的消息（源里全是占位/工具内容？）")

    stamps, prev = [], int(msgs[0].ts_ms or 0)
    for m in msgs:
        ts = int(m.ts_ms or (prev + 1000 if prev else 0))
        if ts <= prev:
            ts = prev + 1000
        stamps.append(ts)
        prev = ts

    lines: list[dict] = []
    parent = None
    for m, ts in zip(msgs, stamps):
        eid = str(uuid.uuid4())
        block_type = "input_text" if m.role == "user" else "output_text"
        row = {
            "id": eid,
            "parentId": parent,
            "timestamp": _iso_ms(ts),
            "type": "message",
            "role": m.role,
            "content": [{"type": block_type, "text": m.text}],
        }
        # 故意不写 providerData：那是"这条回复由哪个模型产生"的实现痕迹。
        # 用户口径是"迁移不关心模型"；产品若需要，会用自己的默认值补。
        lines.append(row)
        parent = eid
    return lines


def _adapter(home: str = "", lineage: str = ""):
    """构造适配器；`home` 非空时**patch 模块级常量**指向隔离目录。"""
    from .._deps import ensure_fork_core
    ensure_fork_core()
    import fork_core.adapter_workbuddy as wbmod   # type: ignore

    prev = (wbmod.DB_PATH, wbmod.PROJECTS_DIR, wbmod.LINEAGE_PATH)
    if home:
        h = os.path.abspath(os.path.expanduser(home))
        wbmod.DB_PATH = os.path.join(h, "workbuddy.db")
        wbmod.PROJECTS_DIR = os.path.join(h, "projects")
        wbmod.LINEAGE_PATH = lineage or os.path.join(h, "fork.lineage.json")
    return wbmod.WorkBuddyAdapter(), prev, wbmod


def _slug(cwd: str) -> str:
    """产品的项目目录名规则：cwd 里的 `/` 换成 `-`（照真机路径抄的）。"""
    return cwd.strip("/").replace("/", "-") or "migrated"


def write(lines: list[dict], home: str, session_id: str, *, project: str = "",
          cwd: str = "") -> str:
    """把转录写进 `projects/<项目>/<会话id>.jsonl`。

    项目目录缺省按 **cwd** 推导（`/a/b` → `a-b`），这样产品自己的路径逻辑能对上；
    写死一个自定义目录会让"库里 cwd"和"文件在哪"两处不一致。
    """
    ad, prev, wbmod = _adapter(home)
    try:
        proj = project or _slug(cwd)
        d = os.path.join(ad.PROJECTS_DIR, proj)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{session_id}.jsonl")
        ad.write_branch(path, lines)
        return path
    finally:
        wbmod.DB_PATH, wbmod.PROJECTS_DIR, wbmod.LINEAGE_PATH = prev


def register(path: str, session_id: str, title: str, *, home: str = "",
             template_id: str | None = None, cwd: str = "") -> str:
    """登记进 `sessions` 表（模板行来自产品自己建的会话）。"""
    ad, prev, wbmod = _adapter(home)
    try:
        if template_id:
            src = ad.load_session_meta(template_id)
        else:
            cur = ad._connect().cursor()
            row = cur.execute(
                "select id from sessions where deleted_at is null "
                "order by updated_at desc limit 1").fetchone()
            if not row:
                raise SystemExit("✗ 目标库里没有现成会话可当模板——先用产品建一条")
            src = ad.load_session_meta(row["id"])
        if src is None:
            raise SystemExit("✗ 读不到模板会话的元数据")
        ad.register_branch(src, session_id, path, title, parent_id=src.id)
        # ③ 覆盖 cwd：模板带过来的是**那条会话的**工作目录
        #    （打分支时正好对；迁移时是别人的目录，必须改成我们要写进去的那个）
        if cwd:
            db = ad._connect()
            try:
                db.execute("UPDATE sessions SET cwd=? WHERE id=?", (cwd, session_id))
                db.commit()
            finally:
                db.close()
        return src.id
    finally:
        wbmod.DB_PATH, wbmod.PROJECTS_DIR, wbmod.LINEAGE_PATH = prev
