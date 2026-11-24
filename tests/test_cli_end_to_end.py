#!/usr/bin/env python3
"""端到端对账：走**真实 CLI 路径**（源适配器 → 渲染 → 落盘），断言前后条数一致。

为什么单独一个文件：现有的往返测试是"渲染器 + 写盘"两段，**绕过了源适配器**。
但真实使用是 `--from <产品> --session <id>`，中间那层（读源、噪声过滤、时间戳补齐）
完全没被测到。pi 在这里同时当源和目标——不需要任何外部产品，就能把整条链路跑通。
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FORK = os.environ.get("FORK_CORE_PATH")
if FORK and FORK not in sys.path:
    sys.path.insert(0, FORK)

try:
    import fork_core  # noqa: F401
    HAS_FORK = True
except Exception:
    HAS_FORK = False

if not HAS_FORK:
    print("跳过：需要 session-fork-core（端到端要走源适配器）")
    raise SystemExit(0)

from session_tape.model import Msg          # noqa: E402
from session_tape.render import pi as pi_render   # noqa: E402

TEXTS = [("user", "第一问：这是一个足够长的提问", 1_700_000_000_000),
         ("assistant", "第一答：足够长的回答内容", 1_700_000_001_000),
         ("user", "第二问：再来一个足够长的提问", 1_700_000_002_000),
         ("assistant", "第二答：再来一个足够长的回答", 1_700_000_003_000)]

# ① 造一条"源"：用 pi 自己的格式写一份（这样源适配器能读，模拟真实来源）
srchome = tempfile.mkdtemp(prefix="e2e-src-")
srcdir = os.path.join(srchome, ".pi", "agent", "sessions", "--e2e--")
os.makedirs(srcdir, exist_ok=True)
src = os.path.join(srcdir, "src.jsonl")
with open(src, "w", encoding="utf-8") as f:
    f.write(pi_render.render([Msg(r, t, ts) for r, t, ts in TEXTS], "/tmp/e2e"))

# ② 走真实 CLI：pi → pi（同产品互迁，只换落点）
dsthome = tempfile.mkdtemp(prefix="e2e-dst-")
outdir = os.path.join(dsthome, "out")
env = dict(os.environ, PI_AGENT_DIR=os.path.dirname(srcdir))
r = subprocess.run([sys.executable, "-m", "session_tape",
                    "--from", "pi", "--session-file", src,
                    "--to", "pi", "--out", outdir, "--cwd", "/tmp/e2e"],
                   cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
assert r.returncode == 0, f"CLI 失败：{r.stdout[-400:]}\n{r.stderr[-400:]}"

produced = [os.path.join(outdir, f) for f in os.listdir(outdir) if f.endswith(".jsonl")]
assert len(produced) == 1, produced
out = produced[0]

# ③ 对账：条数与内容都要一致（ocl-3 那条纪律：迁移前 N，迁移后必须 N）
src_texts = [t for _r, t, _ts in TEXTS]
rows = [json.loads(x) for x in open(out, encoding="utf-8") if x.strip()]
got = []
for o in rows:
    if o.get("type") != "message":
        continue
    m = o.get("message") or {}
    c = m.get("content")
    text = c if isinstance(c, str) else "".join(b.get("text", "") for b in (c or []) if isinstance(b, dict))
    got.append((m.get("role"), text))

assert len(got) == len(src_texts), f"条数对不上：源 {len(src_texts)} → 产物 {len(got)}"
assert [t for _r, t in got] == src_texts, [t for _r, t in got]
assert [rr for rr, _t in got] == [rr for rr, _t, _ts in TEXTS], [rr for rr, _t in got]
print(f"✓ 端到端对账：{len(src_texts)} 条 → 产物 {len(got)} 条，角色与文本逐条一致")

# ④ 再跑一次 CLI，确认同样的输入得到同样的条数（防止"有时多一条占位"这类抖动）
outdir2 = os.path.join(dsthome, "out2")
r2 = subprocess.run([sys.executable, "-m", "session_tape",
                     "--from", "pi", "--session-file", src,
                     "--to", "pi", "--out", outdir2, "--cwd", "/tmp/e2e"],
                    cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
out2 = [os.path.join(outdir2, f) for f in os.listdir(outdir2) if f.endswith(".jsonl")][0]
n2 = sum(1 for x in open(out2, encoding="utf-8") if x.strip() and json.loads(x).get("type") == "message")
assert n2 == len(src_texts), f"两次运行条数不一致：{len(got)} vs {n2}"
print(f"✓ 幂等性：同一输入两次运行条数一致（{n2} 条）")

print("\n✅ 端到端对账通过")
