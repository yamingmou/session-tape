"""目标：Codex（`codex-cli`，含 ChatGPT 桌面端内置的 0.169.x）。

Codex 的会话是**两件套**：
  ① **rollout 文件** —— `$CODEX_HOME/sessions/<YYYY>/<MM>/<DD>/rollout-<ISO>-<thread_id>_<uuid>.jsonl`，
     逐行 `{timestamp, ordinal, type, payload}`；
  ② **`state_5.sqlite` 的 `threads` 一行** —— 产品靠它把会话列出来；没有这行，文件再好也看不见。

所以"迁移过去"= 写文件 + 补那一行。第二件事**不自己发明**：直接复用 `session-fork-core`
的 `register_branch`（那段代码在上游 0.169.1 上验过：复制一条**产品自己建的**记录当模板，
只换 id / 路径 / 标题 / 时间）。

字段口径（照真机样本抄，不猜）：
  · 用户消息的正文块是 `{"type":"input_text"}`，模型回复是 `{"type":"output_text"}`；
  · `session_meta.payload` 里 **不要搬**账号身份（`creator_user_id` / `creator_account_id`）
    与 `base_instructions` —— 前者是别人的账号痕迹，后者是产品的系统提示（属于实现，不属于历史）。
    这两样在注册时由模板行补齐，比我们伪造可信。
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc) \
                   .isoformat(timespec="milliseconds").replace("+00:00", "Z")


def render(msgs, cwd: str, *, title: str = "", thread_id: str | None = None,
           model_provider: str = "openai", cli_version: str = "") -> list[dict]:
    """渲染成 Codex rollout 的行序列（`list[dict]`，由安装器落盘）。"""
    if not msgs:
        raise SystemExit("✗ 没有可搬的消息（源里全是占位/工具内容？）")

    tid = thread_id or str(uuid.uuid4())
    start = int(msgs[0].ts_ms or 0) or int(datetime.now().timestamp() * 1000)
    stamps, prev = [], start
    for m in msgs:
        ts = m.ts_ms or (prev + 1000 if prev else start)
        if ts <= prev:
            ts = prev + 1000
        stamps.append(ts)
        prev = ts

    lines: list[dict] = [{
        "timestamp": _iso(stamps[0]), "ordinal": 0, "type": "session_meta",
        "payload": {
            "session_id": tid, "id": tid, "timestamp": _iso(stamps[0]),
            "cwd": cwd, "runtime_workspace_roots": [cwd],
            "originator": "session-tape", "cli_version": cli_version,
            "source": "cli", "thread_source": "user",
            "model_provider": model_provider,
            "history_mode": "paginated",
        },
    }]

    for i, (m, ts) in enumerate(zip(msgs, stamps), 1):
        block_type = "input_text" if m.role == "user" else "output_text"
        block = {"type": block_type, "text": m.text}
        if block_type == "output_text":
            block["annotations"] = []
            block["logprobs"] = []
        lines.append({
            "timestamp": _iso(ts), "ordinal": i, "type": "response_item",
            "payload": {"type": "message", "role": m.role, "content": [block]},
        })
    return lines


def write(lines: list[dict], codex_home: str, thread_id: str) -> str:
    """按 Codex 的目录与命名惯例落盘，返回绝对路径。"""
    ts = lines[0]["payload"]["timestamp"]
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    d = os.path.join(codex_home, "sessions", f"{dt:%Y}", f"{dt:%m}", f"{dt:%d}")
    os.makedirs(d, exist_ok=True)
    stamp = f"{dt:%Y-%m-%dT%H-%M-%S}"
    path = os.path.join(d, f"rollout-{stamp}-{thread_id}_{uuid.uuid4()}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for o in lines:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    return path


def fill(msgs, target_id: str, *, codex_home: str = "", title: str = "") -> tuple[str, str]:
    """**官方建壳、我们灌内容**：拿一条产品自己建好的会话当容器，只换里面的历史。

    这是最干净的一种落地方式（也是我们踩过坑之后的选择）：
      · 容器由产品自己创建 —— id、cwd、provider、账号、系统提示、项目归属、投影状态
        全都天然正确，我们**不猜也不复制模板**；
      · 我们只做三件必要的事：
        ① 备份原 rollout，再把内容改写成迁移来的历史（`session_meta` 原样保留）；
        ② 把投影状态归零（`(0,0)`），让产品自己从第 0 字节重新解析——
           否则它以为"这段我消费过了"，界面会是空或旧内容；
        ③ 更新列表里显示的三处：标题、预览、首句。

    返回 `(rollout 路径, 备份路径)`。
    """
    try:
        from .._deps import ensure_fork_core
        ensure_fork_core()
        from fork_core.adapter_codex import CodexAdapter      # type: ignore
    except Exception as e:                                     # pragma: no cover
        raise SystemExit(f"✗ 需要 session-fork-core：{e}")

    prev_home = os.environ.get("CODEX_HOME")
    if codex_home:
        os.environ["CODEX_HOME"] = os.path.abspath(os.path.expanduser(codex_home))
    try:
        ad = CodexAdapter()
        path, _cwd = ad.find_transcript(target_id)
        if not path or not os.path.exists(path):
            raise SystemExit(f"✗ 找不到目标会话的 rollout：{target_id}")

        head = json.loads(open(path, encoding="utf-8").readline() or "{}")
        meta = dict(head.get("payload") or {})
        if not meta:
            raise SystemExit("✗ 目标 rollout 首行不是 session_meta，不敢动")

        # 容器元数据原样保留，只保证 history_mode 与"自包含完整历史"一致
        meta["history_mode"] = "paginated"
        start = int(msgs[0].ts_ms or 0) or _ms_from_iso(meta.get("timestamp"))
        stamps, prev = [], start
        for m in msgs:
            ts = m.ts_ms or (prev + 1000 if prev else start)
            if ts <= prev:
                ts = prev + 1000
            stamps.append(ts)
            prev = ts

        lines = [{"timestamp": meta.get("timestamp") or _iso(stamps[0]), "ordinal": 0,
                  "type": "session_meta", "payload": meta}]
        for i, (m, ts) in enumerate(zip(msgs, stamps), 1):
            block = {"type": "input_text" if m.role == "user" else "output_text", "text": m.text}
            if m.role != "user":
                block.update({"annotations": [], "logprobs": []})
            lines.append({"timestamp": _iso(ts), "ordinal": i, "type": "response_item",
                          "payload": {"type": "message", "role": m.role,
                                      "content": [block]}})

        # ① 备份 + 覆盖
        backup = f"{path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        with open(backup, "wb") as f:
            f.write(open(path, "rb").read())
        with open(path, "w", encoding="utf-8") as f:
            for o in lines:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")

        # ② 投影归零
        con = ad._connect(ad.HISTORY_DB)
        try:
            con.execute("INSERT OR REPLACE INTO thread_history_projection_state "
                        "(thread_id, next_rollout_byte_offset, next_rollout_ordinal) VALUES (?,?,?)",
                        (target_id, 0, 0))
            con.commit()
        finally:
            con.close()
        _assert_projection_zero(ad, target_id)      # 同一条代理指标

        # ③ 列表显示
        first_user = next((m.text for m in msgs if m.role == "user"), "")
        con = ad._connect(ad.STATE_DB)
        try:
            now = int(datetime.now().timestamp())
            con.execute("UPDATE threads SET title=COALESCE(NULLIF(?,''), title), preview=?, "
                        "first_user_message=?, updated_at=?, updated_at_ms=?, recency_at_ms=? "
                        "WHERE id=?",
                        (title, title or first_user[:60], first_user, now, now * 1000,
                         now * 1000, target_id))
            con.commit()
        finally:
            con.close()
        return path, backup
    finally:
        if codex_home:
            if prev_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = prev_home


def _ms_from_iso(s: str | None) -> int:
    if not s:
        return 0
    try:
        dt = datetime.strptime(s.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f")
        return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
    except Exception:
        return 0


def _assert_projection_zero(ad, thread_id: str) -> tuple[int, int]:
    """断言 **消费进度为初始值 (0,0)** —— 这是"产品可见"的可自动检查代理指标。

    为什么不直接断言"它出现在列表里"：那要跑产品自己的 UI/索引逻辑，我们做不到，
    而且按接口边界（不承诺可见）本来也不该承诺。但**这一条是能读的**：

        产品以为"这段 rollout 我消费到第 N 字节" ⇒ next_rollout_byte_offset > 0
        ⇒ 新写的内容永远不会被解析 ⇒ 界面空或停在旧内容。

    所以断言 `(0,0)`：**代理指标通过 ≠ 产品可见**，但它失败就一定看不见。
    """
    con = ad._connect(ad.HISTORY_DB)
    try:
        row = con.execute(
            "select next_rollout_byte_offset, next_rollout_ordinal "
            "from thread_history_projection_state where thread_id=?", (thread_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise SystemExit(
            f"✗ 登记后找不到投影状态行（thread {thread_id[:8]}…）⇒ 产品一定看不见这条会话。")
    off, ordn = int(row[0]), int(row[1])
    if (off, ordn) != (0, 0):
        raise SystemExit(
            f"✗ 投影状态不是初始值（{off}, {ordn}）⇒ 产品会以为这段已消费过，界面将为空或旧内容。"
            f"把 next_rollout_byte_offset / next_rollout_ordinal 归零后重试。")
    return off, ordn


def register(path: str, thread_id: str, title: str, *, codex_home: str = "",
             first_user_message: str = "", template_id: str | None = None) -> str:
    """把这条 rollout 登记进产品的 `threads` 表，让它**出现在列表里**。

    复用 `session-fork-core` 的 `register_branch`：它拿一条产品自己建的记录当模板
    （账号、沙箱策略、批准模式、CLI 版本这些"环境事实"都由模板提供），
    只覆盖 id / 路径 / 标题 / 时间，并补上投影状态让产品自己重建。

    ⚠️ 两处**必须自己补**的（fork 的语义与迁移不同，直接复用会错位）：
      ① **`CODEX_HOME` 必须在构造适配器之前设**——适配器在 `__init__` 里读它，
         晚了就会写进默认 `~/.codex`（实测：隔离测试污染了真实库）；
      ② **`first_user_message` / `preview` 必须覆盖成迁移内容的第一句**——
         打分支时"分支的第一句＝源的第一句"，所以模板值正好对；
         迁移时内容不同，照抄会让这条会话在列表里**长得和源会话一模一样**。
    """
    try:
        from .._deps import ensure_fork_core
        ensure_fork_core()
        from fork_core.adapter_codex import CodexAdapter      # type: ignore
        from fork_core.models import SessionMeta              # type: ignore
    except Exception as e:                                     # pragma: no cover
        raise SystemExit(f"✗ 注册需要 session-fork-core：{e}")

    prev_home = os.environ.get("CODEX_HOME")
    if codex_home:
        os.environ["CODEX_HOME"] = os.path.abspath(os.path.expanduser(codex_home))
    try:
        ad = CodexAdapter()          # 直接构造：不吃 get_adapter 的缓存
        # `_thread_rows()` 给的是 sqlite3.Row（没有 .get），先转 dict
        rows = [dict(r) for r in ad._thread_rows()]
        if not rows:
            raise SystemExit("✗ 目标 CODEX_HOME 里没有任何现成会话可当模板——"
                             "先用 codex 自己跑一轮，让产品建一条")
        template = next((r for r in rows if r["id"] == template_id), None) or rows[0]

        src = SessionMeta(id=template["id"], title=template.get("title") or "",
                          cwd=template.get("cwd") or "")
        ad.register_branch(src, thread_id, path, title, parent_id=template["id"])

        # ② 覆盖"首句/预览"：列表里显示的就是它
        if first_user_message:
            con = ad._connect(ad.STATE_DB)
            try:
                con.execute(
                    "UPDATE threads SET first_user_message=?, preview=? WHERE id=?",
                    (first_user_message, title, thread_id))
                con.commit()
            finally:
                con.close()

        # 迁移不是分支：把 register_branch 顺手写下的谱系边摘掉
        # （否则产品若"归档态沿谱系继承"，模板被归档会连带我们的产物）
        from ._lineage import detach
        detach(ad, thread_id)

        # 可见性的可自动代理：投影必须归零（见 _assert_projection_zero 的说明）
        _assert_projection_zero(ad, thread_id)
        return template["id"]
    finally:
        if codex_home:
            if prev_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = prev_home
