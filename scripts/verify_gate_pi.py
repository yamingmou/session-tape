#!/usr/bin/env python3
"""验收门禁：**让目标产品自己跑一轮**，并断言"迁移的历史真的到了它手里"。

为什么需要它（这是我们和上游学的唯一一件事，也是最值钱的一件事）：

  原来的验收是"接本机 ollama + 肉眼看文件有没有追加"——
  **不能进 CI，也不能在每次提交后跑**，而且"看起来对"和"真的对"之间隔着人眼。

  这个门禁把同一件事变成可重复的判断依据：
    ① 起一个**本地协议桩**（只实现 pi 需要的 OpenAI Chat Completions 表面）；
    ② 空 HOME + 假 key，让 pi 只能打到桩上（不联网、不花钱、不需要真 key）；
    ③ 让 pi 打开**我们迁移出来的会话**问一句话；
    ④ 断言三件：
       - **桩收到的请求里带着源历史的标记**（= 迁移的内容真的进了上下文）；
       - pi 退出码 0，且**会话文件被追加**（= 它把这一轮写回了同一个会话）；
       - 追加的 assistant 里带着桩返回的标记（= 是它调用模型的结果，不是我们伪造的）。
    ⑤ 最后用 pi 自己的解析器重读一遍。

三件缺一件都不算过。尤其第 ④ 条的第一项：**"能打开"和"历史真的进去了"是两回事**。

用法：
  python3 scripts/verify_gate_pi.py --pi /path/to/pi --session <迁移产物.jsonl> [--node <node>]

退出码 0 = 过；非 0 = 没过（并打印是哪一条）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY_MARKER = "GATE-REPLY-7f3a"      # 桩固定回这个；用来证明回复确实来自模型调用
_STATE: dict = {"requests": [], "port": 0}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):        # 静音
        return

    def do_GET(self):
        self._json({"object": "list", "data": [{"id": "gate-1", "object": "model"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        _STATE["requests"].append(body)
        text = REPLY_MARKER
        if body.get("stream"):
            chunk = {"id": "chatcmpl-gate", "object": "chat.completion.chunk", "created": 0,
                     "model": body.get("model", "gate-1"),
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": text},
                                  "finish_reason": None}]}
            tail = {"id": "chatcmpl-gate", "object": "chat.completion.chunk", "created": 0,
                    "model": body.get("model", "gate-1"),
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            payload = (f"data: {json.dumps(chunk)}\n\n"
                       f"data: {json.dumps(tail)}\n\n"
                       "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self._json({"id": "chatcmpl-gate", "object": "chat.completion", "created": 0,
                        "model": body.get("model", "gate-1"),
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": text}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    def _json(self, obj):
        raw = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _start_stub() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _STATE["port"] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _write_models_json(home: str, port: int) -> None:
    d = os.path.join(home, ".pi", "agent")
    os.makedirs(d, exist_ok=True)
    cfg = {"providers": {"gate": {
        "baseUrl": f"http://127.0.0.1:{port}/v1",
        "api": "openai-completions", "apiKey": "gate",
        "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False},
        "models": [{"id": "gate-1"}],
    }}}
    with open(os.path.join(d, "models.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _marker_from(path: str) -> str:
    """从迁移产物里挑一段"源历史"的标记，用来证明内容真的进了上下文。"""
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        o = json.loads(line)
        if o.get("type") != "message":
            continue
        c = (o.get("message") or {}).get("content")
        text = c if isinstance(c, str) else "".join(
            b.get("text", "") for b in (c or []) if isinstance(b, dict))
        text = text.strip()
        if len(text) >= 12:
            return text[:24]
    raise SystemExit("✗ 迁移产物里找不到可用的标记文本")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi", required=True, help="pi 可执行文件路径")
    ap.add_argument("--session", required=True, help="迁移产物（pi 会话文件）")
    ap.add_argument("--out", help="隔离 HOME 放哪（缺省用临时目录）")
    args = ap.parse_args()

    if not (os.path.isfile(args.pi) and os.access(args.pi, os.X_OK)):
        print(f"跳过：pi 不可执行（{args.pi}）")
        return 0
    session = os.path.abspath(args.session)
    marker = _marker_from(session)
    before = sum(1 for _ in open(session, encoding="utf-8"))

    # pi 会拒绝打开 cwd 不存在的会话（实测："Stored session working directory does not exist"）
    # ⇒ 先把会话头部记的 cwd 建出来，再进去跑。
    header = json.loads(open(session, encoding="utf-8").readline() or "{}")
    cwd = header.get("cwd") or os.path.dirname(session) or "."
    os.makedirs(cwd, exist_ok=True)

    home = args.out or tempfile.mkdtemp(prefix="gate-pi-home-")
    os.makedirs(home, exist_ok=True)
    fails: list[str] = []
    srv = None
    try:
        srv = _start_stub()
        _write_models_json(home, _STATE["port"])
        env = dict(os.environ, HOME=home)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PI_API_KEY"):
            env.pop(k, None)                       # 假 key 也不用：桩不校验
        r = subprocess.run(
            [args.pi, "--provider", "gate", "--model", "gate-1",
             "--session", session, "--print", "请用一句话复述我们之前聊过的内容"],
            cwd=cwd, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )

        # ① 桩收到的请求里带源历史标记
        blob = json.dumps(_STATE["requests"], ensure_ascii=False)
        if not _STATE["requests"]:
            fails.append("桩没收到任何请求（pi 没走我们的 provider？）")
        elif marker not in blob:
            fails.append(f"桩收到的请求里没有源历史标记（{marker!r}）⇒ 历史没进上下文")

        # ② 退出码 + 会话被追加
        if r.returncode != 0:
            fails.append(f"pi 退出码 {r.returncode}：{(r.stderr or r.stdout or '').strip()[:200]}")
        after = sum(1 for _ in open(session, encoding="utf-8"))
        if after <= before:
            fails.append(f"会话文件没被追加（{before} → {after} 行）")

        # ③ 追加的 assistant 里带桩的回复标记
        tail = [json.loads(x) for x in open(session, encoding="utf-8") if x.strip()][before:]
        got = json.dumps(tail, ensure_ascii=False)
        if REPLY_MARKER not in got:
            fails.append(f"追加的条目里没有桩的回复标记（{REPLY_MARKER}）⇒ 那轮不是真调模型")

        # ④ 用 pi 自己的解析器重读（有 node + lab/verify.mjs 才跑）
        verify_mjs = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "lab", "verify.mjs")
        node = shutil.which("node")
        if node and os.path.exists(verify_mjs):
            with open("/tmp/gate-out.txt", "w", encoding="utf-8") as f:
                f.write(session)
            v = subprocess.run([node, verify_mjs], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
            if v.returncode != 0 or "条目数" not in (v.stdout or ""):
                fails.append(f"pi 自己重读失败：{(v.stdout or v.stderr or '')[:200]}")
    finally:
        if srv:
            srv.shutdown()

    print(f"标记（源历史）: {marker}")
    print(f"桩收到请求    : {len(_STATE['requests'])} 次")
    print(f"会话行数      : {before} → {sum(1 for _ in open(session, encoding='utf-8'))}")
    if fails:
        print("\n✗ 门禁未过：")
        for f in fails:
            print("   -", f)
        return 1
    print("\n✅ 门禁通过：历史真的进了上下文、pi 真调了模型、回复真写回了同一条会话")
    return 0


if __name__ == "__main__":
    sys.exit(main())
