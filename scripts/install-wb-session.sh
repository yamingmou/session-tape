#!/bin/sh
# 把 Qwen 的「插件开发者 2」迁进 WorkBuddy（一条命令装完 + 自证）
#
# 为什么要脚本：写 `~/.workbuddy/projects/*/*.jsonl` 被权限规则挡住，Agent 侧无法代写；
# 这个脚本把「渲染 → 写转录 → 登记 sessions 行 → 自证」四步合成一步。
#
# 用法： sh ~/opena/工程-迁移录音机/scripts/install-wb-session.sh [--cwd 目录] [--limit N]
set -e

FORK="${FORK_CORE_PATH:-/Users/maxwell/opena/工程-fork任务/dev-worktree/session-fork-2.4.8-dev}"
PKG="$(cd "$(dirname "$0")/.." && pwd)"
QWEN_SESSION="${QWEN_SESSION:-mvfhzb4t961plcac}"
WB_HOME="${WB_HOME:-$HOME/.workbuddy}"
CWD="${CWD:-/Users/maxwell/openqw}"
TITLE="${TITLE:-插件开发者 2（Qwen→WorkBuddy）}"

[ -d "$FORK/fork_core" ] || {
  echo "✗ 找不到 session-fork-core：$FORK"
  echo "  用 FORK_CORE_PATH=<路径> 指定，或先 git clone 一份"
  exit 1
}

echo "→ 源会话 : $QWEN_SESSION"
echo "→ 落点   : $WB_HOME/projects/ + workbuddy.db"
echo "→ 目录   : $CWD"
echo

FORK_CORE_PATH="$FORK" PYTHONPATH="$FORK" \
  python3 -m session_tape \
    --from qwen --session "$QWEN_SESSION" \
    --to workbuddy --install-wb-home "$WB_HOME" \
    --cwd "$CWD" --name "$TITLE"

echo
echo "→ 自证：查 sessions 表里这一行"
FORK_CORE_PATH="$FORK" PYTHONPATH="$FORK" python3 - "$WB_HOME" "$TITLE" <<'PY'
import os, sqlite3, sys
home, title = sys.argv[1], sys.argv[2]
db = os.path.join(home, "workbuddy.db")
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cols = [r[1] for r in con.execute("PRAGMA table_info(sessions)")]
row = con.execute(
    "select * from sessions where title=? order by rowid desc limit 1", (title,)).fetchone()
if not row:
    print("  ✗ sessions 表里没有这一行 —— 请把上面的输出发我")
    raise SystemExit(2)
d = dict(row)
print(f"  ✓ 已登记：id={d.get('id')}")
print(f"    标题   = {d.get('title')}")
for k in ("project_path", "cwd", "created_at", "updated_at", "message_count"):
    if k in d and d[k] not in (None, ""):
        print(f"    {k:11}= {str(d[k])[:70]}")
# 转录文件是否真的落盘且行数对得上
pid = d.get("id")
cands = [os.path.join(root, f"{pid}.jsonl")
         for root, _dirs, files in os.walk(os.path.join(home, "projects"))]
real = [c for c in cands if os.path.exists(c)]
if real:
    n = sum(1 for line in open(real[0], encoding="utf-8") if line.strip())
    print(f"  ✓ 转录文件：{real[0]}")
    print(f"    行数    = {n}")
else:
    print("  ⚠ 没找到对应转录文件（可能在别的项目目录下）")
con.close()
PY

echo
echo "→ 下一步：重启 WorkBuddy（⌘Q 后重开），在项目 openqw 下查看该会话"
