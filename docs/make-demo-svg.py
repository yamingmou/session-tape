#!/usr/bin/env python3
"""把真实终端输出渲染成一张 SVG，供 README 使用。

为什么要脚本而不是手画：**图里的内容必须是真的**。输出变了，重跑一次脚本，
图跟着变；手画的图迟早会和实际行为对不上，那时候它就从"演示"变成"误导"。

用法：
  python3 docs/make-demo-svg.py > docs/demo.svg
"""
from __future__ import annotations

import html
import subprocess
import sys

CMD = f"{sys.executable} -m session_tape demo"


def main() -> int:
    try:
        out = subprocess.run(CMD.split(), capture_output=True, text=True,
                             encoding="utf-8", timeout=120).stdout
    except Exception as e:
        print(f"跑不动 demo：{e}", file=sys.stderr)
        return 1
    lines = [ln.rstrip() for ln in out.strip().split("\n") if ln.strip()]
    if not lines:
        print("demo 没有输出", file=sys.stderr)
        return 1

    # 只看前若干行，太长在 README 里反而没人看
    lines = lines[:16]

    pad, lh, fs = 22, 20, 13
    title_h = 34
    # 等宽 13px 的字符宽约 7.9px：先按最长行算宽，再按宽度反截断——
    # 否则长行会顶出右边框（第一版就是这样，靠肉眼才发现）。
    maxlen = min(max(len(ln) for ln in lines), 108)
    w = max(560, int(pad * 2 + maxlen * 8.0))   # 8.0 = 保守字符宽（等宽 13px 实测 7.6~7.9）
    maxlen = max(40, (w - pad * 2 - 12) // 8)   # 再按真实宽度回截，留 12px 右边距
    h = title_h + len(lines) * lh + pad

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">',
        f'<rect width="{w}" height="{h}" rx="10" fill="#12151b"/>',
        f'<rect width="{w}" height="{title_h}" rx="10" fill="#1b2029"/>',
        f'<rect y="{title_h - 10}" width="{w}" height="10" fill="#1b2029"/>',
        f'<circle cx="20" cy="{title_h // 2}" r="5" fill="#ff5f57"/>',
        f'<circle cx="38" cy="{title_h // 2}" r="5" fill="#febc2e"/>',
        f'<circle cx="56" cy="{title_h // 2}" r="5" fill="#28c840"/>',
        f'<text x="{w // 2}" y="{title_h // 2 + 4}" fill="#8b95a5" font-size="12" '
        f'text-anchor="middle">session-tape demo</text>',
    ]
    for i, ln in enumerate(lines):
        y = title_h + pad // 2 + (i + 1) * lh - 6
        color = "#7ee787" if ln.startswith("✓") or "✅" in ln else "#c9d4e3"
        if ln.startswith("目标") or ln.startswith("---"):
            color = "#8b95a5"
        parts.append(f'<text x="{pad}" y="{y}" fill="{color}" font-size="{fs}">'
                     f'{html.escape(ln[:maxlen])}</text>')
    parts.append("</svg>")
    print("\n".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
