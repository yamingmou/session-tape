#!/usr/bin/env python3
"""OpenCode 引擎的契约测试（读 / 写 / 两代存储）。

**验收等级 L2**：写进真实库的**副本**，再用本仓库的读器读回，内容逐条一致。
本机没有 OpenCode CLI，所以"产品界面里能不能列出"这一层**未验**（不假装验过）。

为什么专门测"两代都写"：这个库有 `session/message/part` 与 `session_v2/session_message`
两代，**同一批会话可能只有其中一代**。只写一代就是押注产品认哪一代——押错的表现是
"文件在、产品看不见"，正是我们反复踩的那一类。
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_tape.engines import opencode          # noqa: E402
from session_tape.model import Msg                 # noqa: E402

MSGS = [Msg("user", "第一问：这是一个足够长的提问", 1_700_000_000_000),
        Msg("assistant", "第一答：足够长的回答内容", 1_700_000_001_000),
        Msg("user", "第二问：再来一个足够长的提问", 1_700_000_002_000)]

src = opencode.find_db()
if not src:
    print("跳过：本机没有 OpenCode 库（找不到 opencode.db）")
    raise SystemExit(0)

# ① 在副本上写，绝不碰真实库
tmp = tempfile.mkdtemp(prefix="oc-engine-")
db = os.path.join(tmp, "opencode.db")
shutil.copy(src, db)
before = sqlite3.connect(db).execute("select count(*) from session").fetchone()[0]

sid = opencode.write_msgs(MSGS, db, title="契约测试｜迁移", cwd="/tmp/oc-cwd")
assert sid.startswith("ses_"), sid

# ② 两代都要有行
con = sqlite3.connect(db)
n_session = con.execute("select count(*) from session where id=?", (sid,)).fetchone()[0]
n_legacy = con.execute("select count(*) from message where session_id=?", (sid,)).fetchone()[0]
n_v2 = con.execute("select count(*) from session_message where session_id=?", (sid,)).fetchone()[0]
has_v2_table = con.execute(
    "select 1 from sqlite_master where type='table' and name='session_v2'").fetchone() is not None
n_sess2 = con.execute("select count(*) from session_v2 where id=?", (sid,)).fetchone()[0] if has_v2_table else 0
assert n_session == 1, n_session
assert n_legacy == len(MSGS), n_legacy
if has_v2_table:
    assert n_sess2 == 1, n_sess2
    assert n_v2 == len(MSGS), n_v2
print(f"✓ 两代都写了：session={n_session} legacy_message={n_legacy} "
      f"session_v2={n_sess2} session_message={n_v2}")

# ③ 读回逐条一致（走 v2 优先的读路径）
back = opencode.read_msgs(db, sid)
assert [m.role for m in back] == [m.role for m in MSGS], back
assert [m.text for m in back] == [m.text for m in MSGS], back
print(f"✓ 读回 {len(back)} 条，角色与文本逐条一致")

# ④ 时间戳单调，且不落到纪元
ts = [m.ts_ms for m in back]
assert ts == sorted(ts) and ts[0] > 1_600_000_000_000, ts
print("✓ 时间戳单调且在合理区间（不是 1970）")

# ⑤ 写入不破坏别人的会话（原有条数 +1，不是覆盖）
after = sqlite3.connect(db).execute("select count(*) from session").fetchone()[0]
assert after == before + 1, (before, after)
print(f"✓ 只新增（{before} → {after}），没有覆盖已有会话")

# ⑥ 源读器能读真实会话（不是只能读自己写的）
for real_sid, _title, _ts in opencode.list_sessions(src, 8):
    got = opencode.read_msgs(src, real_sid)
    if got:
        print(f"✓ 真实会话可读：{real_sid[:18]}… {len(got)} 条，首条[{got[0].role}]")
        break
else:
    raise AssertionError("真实库里没有一条能读出来，读器可能有问题")

print("\n✅ OpenCode 引擎通过（L2：库副本写入并读回；界面可见未验）")
