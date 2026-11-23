"""目标：Claude Code（`~/.claude/projects/<转义 cwd>/<sessionId>.jsonl`）。

行形状取自**真机夹具**（session-fork-core 的 claude 适配器测试里那份，不是文档推演）：

```json
{"type":"user|assistant", "uuid":<uuid4>, "parentUuid":<上一条 uuid|null>,
 "sessionId":<会话 id>, "cwd":<工作目录>, "timestamp":<ISO>,
 "message":{"role":..., "content":[{"type":"text","text":...}]}}
```

与 pi / codex 的两处关键差别：
  · 结构是**树**（`parentUuid`），不是自增序号；线性历史就是一条链；
  · 会话文件放在**按 cwd 转义出来的目录**里（`/Users/a/b` → `-Users-a-b`）。
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc) \
                   .isoformat(timespec="milliseconds").replace("+00:00", "Z")


def project_dir_name(cwd: str) -> str:
    """产品的目录转义：`/` 和 `.` 都变 `-`（`/Users/a/b` → `-Users-a-b`）。"""
    return cwd.replace("/", "-").replace(".", "-") or "-"


def render(msgs, cwd: str, *, title: str = "", session_id: str | None = None) -> list[dict]:
    if not msgs:
        raise SystemExit("✗ 没有可搬的消息（源里全是占位/工具内容？）")

    sid = session_id or str(uuid.uuid4())
    stamps, prev = [], int(msgs[0].ts_ms or 0) or int(datetime.now().timestamp() * 1000)
    for m in msgs:
        ts = int(m.ts_ms or (prev + 1000 if prev else 0))
        if ts <= prev:
            ts = prev + 1000
        stamps.append(ts)
        prev = ts

    lines, parent = [], None
    for m, ts in zip(msgs, stamps):
        mid = str(uuid.uuid4())
        lines.append({
            "type": m.role,
            "uuid": mid,
            "parentUuid": parent,
            "sessionId": sid,
            "cwd": cwd,
            "timestamp": _iso(ts),
            "message": {"role": m.role, "content": [{"type": "text", "text": m.text}]},
        })
        parent = mid
    return lines


def write(lines: list[dict], out: str, session_id: str, *, cwd: str = "") -> str:
    """落到 `projects/<转义 cwd>/<sessionId>.jsonl`；`out` 是 `~/.claude` 这一层。"""
    base = os.path.join(os.path.expanduser(out), "projects",
                        project_dir_name(cwd or "/"))
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{session_id}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for o in lines:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    return path


def register(path: str, session_id: str, title: str, *, claude_dir: str = "",
             template_id: str | None = None) -> str:
    """登记（`~/.claude` 里另有历史索引时由适配器补）。

    ⚠️ 本机没有装 Claude Code，**登记这条路径没有真机验过**，只是复用适配器的实现；
    没有现成会话当模板时会明确失败，而不是伪造。
    """
    try:
        from fork_core.adapter_claude_code import ClaudeCodeAdapter   # type: ignore
        from fork_core.models import SessionMeta                      # type: ignore
    except Exception as e:                                            # pragma: no cover
        raise SystemExit(f"✗ 登记需要 session-fork-core：{e}")

    ad = ClaudeCodeAdapter()
    tid = template_id
    if not tid:
        base = os.path.join(os.path.expanduser(claude_dir or "~/.claude"), "projects")
        found = []
        for root, _dirs, files in os.walk(base):
            found += [f[:-6] for f in files if f.endswith(".jsonl")]
            if len(found) > 5:
                break
        if not found:
            raise SystemExit("✗ 目标 ~/.claude 里没有现成会话可当模板——先用 Claude Code 跑一轮")
        tid = found[0]
    ad.register_branch(SessionMeta(id=tid, title=""), session_id, path, title, parent_id=tid)
    return tid
