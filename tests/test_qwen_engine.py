#!/usr/bin/env python3
"""Qwen（QwenWorkCN）引擎契约测试。

自带夹具（不依赖本机装 Qwen），断言四件事：
  ① 读：按 `sequence` 排序，`parts` 里只取文本块，`tool-*` / `error` 跳过；
  ② 写：chats + sub_chats + messages 三张表都要有行（少一张产品就认不全）；
  ③ ⭐ `searchable_text` 必须填 —— FTS 触发器只把它塞进 `messages_fts`，
     不填的表现是"消息在界面上有、但搜不到"；
  ④ 时间戳按**秒**（产品用秒，不是毫秒——写毫秒会显示成 5 万年后）。
另外若本机有真库，做一次只读冒烟（不写）。
"""
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_tape.engines import qwen      # noqa: E402
from session_tape.model import Msg          # noqa: E402

SCHEMA = """
create table chats (id text primary key not null, name text, project_id text not null,
  created_at integer, updated_at integer, archived_at integer, worktree_path text, branch text,
  base_branch text, pr_url text, pr_number integer, additional_directories text,
  output_directory text, source text, wecom_account_id text, wecom_user_id text,
  chat_type text default 'task', ext text, source_chat_id text, deleted_at integer,
  local_project_id text, version integer default 0,
  session_namespace text not null default 'standard', identity_key text);
create table sub_chats (id text primary key not null, name text, chat_id text not null,
  session_id text, mode text not null default 'agent', messages text not null default '[]',
  created_at integer, updated_at integer, stream_id text, feedback text default 'none',
  model_level text, ext text, message_feedbacks text default '{}');
create table messages (id text primary key not null, message_id text not null,
  chat_id text not null, sub_chat_id text not null, sequence integer not null,
  role text not null, parts text not null default '[]', metadata text not null default '{}',
  searchable_text text, search_status text not null default 'ready',
  created_at integer, updated_at integer);
create virtual table messages_fts using fts5(
  searchable_text, chat_id, sub_chat_id, message_id, role);
create trigger messages_fts_ai after insert on messages begin
  insert into messages_fts(rowid, searchable_text, chat_id, sub_chat_id, message_id, role)
  values (new.rowid, new.searchable_text, new.chat_id, new.sub_chat_id, new.message_id, new.role);
end;
"""

now = int(__import__("time").time())
tmp = tempfile.mkdtemp(prefix="qw-test-")
db = os.path.join(tmp, "agents.db")
con = sqlite3.connect(db)
con.executescript(SCHEMA)
con.execute("insert into chats (id, name, project_id, created_at, updated_at) values "
            "('mwsrc000000000', '源会话', 'proj1', ?, ?)", (now, now))
con.execute("insert into sub_chats (id, chat_id, session_id, created_at, updated_at) values "
            "('mwsub000000000', 'mwsrc000000000', 'sess-1', ?, ?)", (now, now))
rows = [("user", [{"type": "text", "text": "第一问"}], "第一问"),
        ("assistant", [{"type": "tool-Thinking", "toolCallId": "t1"},
                       {"type": "text", "text": "第一答"}], "第一答"),
        ("assistant", [{"type": "error", "text": "402"}], ""),
        ("user", [{"type": "text", "text": "第二问"}], "第二问")]
for i, (role, parts, searchable) in enumerate(rows):
    con.execute("insert into messages (id, message_id, chat_id, sub_chat_id, sequence, role, parts, "
                "metadata, searchable_text, created_at, updated_at) values (?,?,?,?,?,?,?,'{}',?,?,?)",
                (f"msg{i:06d}", f"mid{i:06d}", "mwsrc000000000", "mwsub000000000", i, role,
                 json.dumps(parts, ensure_ascii=False), searchable, now + i, now + i))
con.commit()
con.close()

# ① 读：只取文本块，跳过 tool / error
got = qwen.read_msgs(db, "mwsrc000000000")
assert [m.role for m in got] == ["user", "assistant", "user"], [m.role for m in got]
assert got[1].text == "第一答", got[1].text
print("✓ 读：跳过 tool-* 与 error，只留文本；按 sequence 排序")

# ② 写：三张表都要有行
msgs = [Msg("user", "迁移第一问", 1_700_000_000_000),
        Msg("assistant", "迁移第一答", 1_700_000_600_000)]
cid = qwen.write_msgs(msgs, db, title="契约测试", cwd="/tmp/proj")
con = sqlite3.connect(db)
assert con.execute("select count(*) from chats where id=?", (cid,)).fetchone()[0] == 1
assert con.execute("select count(*) from sub_chats where chat_id=?", (cid,)).fetchone()[0] == 1
n_msg = con.execute("select count(*) from messages where chat_id=?", (cid,)).fetchone()[0]
assert n_msg == 2, n_msg
print("✓ 写：chats + sub_chats + messages 三张表都有行")

# ③ searchable_text → FTS
n_fts = con.execute("select count(*) from messages_fts where chat_id=?", (cid,)).fetchone()[0]
assert n_fts == n_msg, f"FTS 未同步：{n_fts}/{n_msg} —— 搜索会找不到"
empty = con.execute("select count(*) from messages where chat_id=? and "
                    "(searchable_text is null or searchable_text='')", (cid,)).fetchone()[0]
assert empty == 0, "searchable_text 为空 ⇒ 消息可见但搜不到"
print(f"✓ 搜索：searchable_text 已填，FTS {n_fts}/{n_msg} 条同步")

# ④ 时间戳按秒
ts = con.execute("select created_at from messages where chat_id=? order by sequence limit 1",
                 (cid,)).fetchone()[0]
assert ts == 1_700_000_000, ts
print(f"✓ 时间戳按秒：{ts}（写毫秒会被产品显示成几万年后）")
con.close()

# 读回一致
back = qwen.read_msgs(db, cid)
assert [m.text for m in back] == [m.text for m in msgs], back
print("✓ 读回逐条一致")

# 真库只读冒烟（有就顺带验，不写）
real = qwen.find_db()
if real and os.path.abspath(real) != os.path.abspath(db):
    rows = qwen.list_sessions(real, 5)
    readable = [(cid_, name) for cid_, name, _ts in rows if qwen.read_msgs(real, cid_)]
    if readable:
        cid_, name = readable[0]
        print(f"✓ 真库只读冒烟：{cid_} 可读（{len(qwen.read_msgs(real, cid_))} 条，{name[:16]}）")

print("\n✅ Qwen 引擎契约测试通过（界面可见未验，属 L2）")
