#!/bin/sh
# session-tape 一键安装
#
#   curl -fsSL https://raw.githubusercontent.com/yamingmou/session-tape/main/install.sh | sh
#
# 只做三件事：检查 Python 版本 → 装本体与适配器层 → 打印下一步。
# 不想让它动你的环境时，加 --check 只检查不安装。
set -eu

PKG="session-tape"                 # 已发布在 PyPI
REPO="git+https://github.com/yamingmou/session-tape.git"   # PyPI 不可达时兜底
DEPS="https://github.com/yamingmou/session-fork-core.git"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

# ---- 1. Python ----
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || die "没找到 Python。需要 3.10 或更新版本：https://www.python.org/downloads/"

"$PY" - <<'CHECK' || die "Python 版本太旧（需要 3.10+）。"
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
CHECK
say "✓ Python $($PY -c 'import sys;print("%d.%d"%sys.version_info[:2])')"

# ---- 2. 装 ----
# 优先用 uv / pipx（装在独立环境里，不污染系统 Python），否则退回 pip --user
if command -v uv >/dev/null 2>&1; then
  INSTALLER="uv tool install"
elif command -v pipx >/dev/null 2>&1; then
  INSTALLER="pipx install"
else
  INSTALLER="$PY -m pip install --user --upgrade"
fi

say "→ 用：$INSTALLER"
if [ "$CHECK_ONLY" = "1" ]; then
  say "（--check：只检查，不安装）"
  say "  将要安装：${PKG}（PyPI）；失败则 ${REPO}"
  say "  依赖：    $DEPS"
  exit 0
fi

# shellcheck disable=SC2086
# 先走 PyPI（快、不需要 git）；不通再退回 git 源
$INSTALLER "$PKG" || $INSTALLER "$REPO" \
  || die "安装失败。可手动执行：
  $INSTALLER $PKG
  或  $INSTALLER $REPO"

# ---- 3. 验 ----
say ""
if command -v session-tape >/dev/null 2>&1; then
  say "✓ 装好了：$(command -v session-tape)  $(session-tape --version 2>/dev/null || true)"
  say ""
  say "下一步（任选）："
  say "  session-tape demo     # 离线看效果，不需要装任何产品"
  say "  session-tape list     # 看本机有哪些会话"
  say "  session-tape          # 向导：问你要从哪搬到哪"
else
  say "装完了，但 session-tape 不在 PATH 里。"
  say "如果用的是 pip --user，把用户级 bin 目录加进 PATH 后重开终端："
  say "  $PY -m site --user-base    # 该目录下的 bin/ 就是"
fi
