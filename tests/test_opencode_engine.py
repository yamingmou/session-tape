#!/usr/bin/env python3
"""OpenCode 引擎：写 v2 + **用产品自己验收**（这是唯一算数的验收）。

判据（都靠产品自己的 CLI，不靠我们的读器）：
  ① `opencode session list` 在目标目录里**列得出来**；
  ② `opencode session export <id>` **导得出来**，且用户消息逐条一致。

⚠️ 这条能力是试出来的，不是设计出来的。走过的弯路记在这里，免得以后有人重走：

  1. 手写旧一代 `session/message/part` ＋ 新一代 `session_v2/session_message` —— 两代都补，
     我方读器读得回，但 `session list` **空**。原因是缺 `project` 行（产品按目录→项目过滤）；
  2. 官方 `session import` 存在，JSON 照 `session export` 抄，**对新会话一律 Bad Request**
     （换 id / 不给 id / 去 projectID / 去 permissions / --standalone 全试过）；
  3. 最后靠**产品自己建的一条会话当基准**（用户在客户端里新建「测试输出1」）diff 出来：
     · 新版只在 `session_v2`，`session` 表里 0 行；
     · 必须有 `project` 行 —— 而它是产品建的：在目标目录跑一次 `session list` 就会生成；
     · user 的 data 要带 `metadata.displayText/agent/model`；assistant 带 `content` 块
       与 `time.streamed/completed/finish`；末尾要有 `idle` 消息；
     · **assistant 在 export 里 `text` 本来就是 None**（真基准也这样），不是我们的 bug。
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_tape.engines import opencode          # noqa: E402
from session_tape.model import Msg                 # noqa: E402

MSGS = [Msg("user", "第一问：这是一个足够长的提问", 1_700_000_000_000),
        Msg("assistant", "第一答：足够长的回答内容", 1_700_000_001_000),
        Msg("user", "第二问：再来一个足够长的提问", 1_700_000_002_000)]

src = opencode.find_db()
cli = opencode.find_cli()
if not src:
    print("跳过：本机没有 OpenCode 库")
    raise SystemExit(0)

# ① 在**库副本**上写（不碰真实库），目标目录用临时目录
tmp = tempfile.mkdtemp(prefix="oc-v2-")
db = os.path.join(tmp, "opencode.db")
shutil.copy(src, db)

# ⚠️ 目标目录必须**客户端已认可**（有 project 行）：`project` 行只有产品自己会建，
# 我们算不出来（13 个已知行、7 种哈希变体 0 命中）。这里借真实库里第一个可用目录。
dirs = opencode.known_directories(db)
if not dirs:
    print("跳过：库里没有任何可用目录")
    raise SystemExit(0)
workdir = dirs[0]

sid = opencode.write_v2(MSGS, db, title="契约测试｜v2", cwd=workdir, cli=cli)
assert sid.startswith("ses_"), sid

con = sqlite3.connect(db)
n_v2 = con.execute("select count(*) from session_v2 where id=?", (sid,)).fetchone()[0]
n_legacy = con.execute("select count(*) from session where id=?", (sid,)).fetchone()[0]
n_msg = con.execute("select count(*) from session_message where session_id=?", (sid,)).fetchone()[0]
types = [r[0] for r in con.execute("select type from session_message where session_id=? order by seq", (sid,))]
assert n_v2 == 1, n_v2
assert n_legacy == 0, f"新版只写 v2，不该写 session 表（实际 {n_legacy} 行）"
assert n_msg == len(MSGS) + 1, n_msg
assert types == ["user", "assistant", "user", "idle"], types
print(f"✓ 只写 v2：session_v2=1 / session 表=0 / session_message={n_msg}（末尾有 idle）")

# ② 我方读器能读回（这只是自证，不算验收）
back = opencode.read_msgs(db, sid)
assert [m.text for m in back] == [m.text for m in MSGS], back
print(f"✓ 我方读器读回 {len(back)} 条（自证，不算验收）")

# ③ 产品自己的验收：**仅限于真实库**（实测：opencode CLI 不认 XDG_DATA_HOME，
#    它永远读 ~/.local/share/opencode/opencode.db ⇒ 用副本库根本验不了，
#    强跑只会把测试数据写进用户的真实库）。所以默认跳过，用环境变量显式开启。
if not (cli and os.environ.get("SESSION_TAPE_PRODUCT_CHECK") == "1"):
    print("跳过产品验收：需要 SESSION_TAPE_PRODUCT_CHECK=1（会写入真实库，所以默认不打）")
    env = None
if env is not None:
    lst = subprocess.run([cli, "session", "list"], cwd=workdir, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    listed = sid in (lst.stdout or "")
    print(f"{'✓' if listed else '✗'} 产品 session list {'有' if listed else '没有'}这条")
    assert listed, f"产品列不出来：{(lst.stdout or lst.stderr)[:200]}"
    exp = subprocess.run([cli, "session", "export", sid], cwd=workdir, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert exp.returncode == 0, (exp.stdout + exp.stderr)[-300:]
    doc = json.loads(exp.stdout)
    got = [m.get("text") for m in doc["messages"] if m.get("type") == "user"]
    assert got == [m.text for m in MSGS if m.role == "user"], got
    print(f"✓ 产品 export 导得出，用户消息逐条一致（{len(doc['messages'])} 条消息）")

if env is not None:
    print("\n✅ OpenCode 引擎通过（L3：产品自己列出并导出）")
else:
    print("\n✅ 结构层面通过（L2 自证）；产品可见性**本次未验** —— 见上面那行跳过原因")
