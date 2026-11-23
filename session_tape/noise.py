"""噪声过滤：搬之前先把"不是对话"的东西拿掉。

三类噪声（都是真数据里撞出来的，不是假想）：

1. **占位文本**：用户中断时，产品会写一条 `Interrupted by user` / `[Request interrupted by user]`
   当作 assistant 的内容。直接搬过去，新产品的模型会以为"上一条回答就是这个"。
2. **平台包裹**：源产品把用户输入包在 `<system-reminder>…</system-reminder>` 里，
   真正的指令在 `<user_query>…</user_query>` 内部。整段搬过去等于把 A 的内部机制带进 B。
3. **重复投递**：同一句话在源里出现两次（用户重发/重试）——照搬就是两条一样的问句。

原则：**宁可少搬一条，不要搬错一条**。丢了多少条、为什么，要能被打印出来核对。
"""
from __future__ import annotations

import re

# 整条等于这些内容 ⇒ 不是对话内容
_PLACEHOLDER_EXACT = {
    "Interrupted by user",
    "[Request interrupted by user]",
    "[Request interrupted by user for tool use]",
    "No response requested.",
    "Continue",
}

# 挂在开头且整条就是它的形态。
# ⚠️ 首版写成 `interrupted by user[^\]]*`，把「Interrupted by user 之后我怎么恢复？」
#    这种真问题也吞了（负向断言抓到的）。占位只有这几种确切形态，多一个字都不算。
_PLACEHOLDER_RE = re.compile(
    r"^\s*\[?\s*(?:request\s+)?interrupted\s+by\s+user(?:\s+for\s+tool\s+use)?\s*\]?\s*$",
    re.IGNORECASE,
)

# 平台包裹：整块 <tag ...>…</tag>
_WRAPPER_RE = re.compile(r"^\s*<([a-zA-Z][\w-]*)(?:\s[^>]*)?>.*?</\1>\s*$", re.DOTALL)
_USER_QUERY_RE = re.compile(r"<user_query>(.*?)</user_query>", re.DOTALL)


def strip_wrappers(text: str) -> str:
    """剥掉平台包裹，只留人写的那句。有 `<user_query>` 就取它内部的。"""
    m = _USER_QUERY_RE.search(text)
    if m:
        return m.group(1).strip()
    out = text.strip()
    # 可能套了多层（外层 system-reminder 里再包一层），反复剥
    for _ in range(4):
        m = _WRAPPER_RE.match(out)
        if not m:
            break
        out = (m.group(0)[m.group(0).find(">") + 1: m.group(0).rfind("<")]).strip()
    return out


def is_placeholder(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if t in _PLACEHOLDER_EXACT:
        return True
    return bool(_PLACEHOLDER_RE.match(t))


def clean(msgs, stats: dict[str, int] | None = None):
    """按顺序过滤 + 合并重复。

    返回新的 `Msg` 列表；`stats` 里累加各种丢弃原因的条数（便于打印核对）。
    """
    from .model import Msg

    stats = stats if stats is not None else {}
    out: list[Msg] = []
    for m in msgs:
        text = strip_wrappers(m.text) if m.role == "user" else m.text.strip()
        if not text or is_placeholder(text):
            key = "占位/中断文本"
            stats[key] = stats.get(key, 0) + 1
            continue
        if out and out[-1].role == m.role and out[-1].text.strip() == text:
            key = "重复投递（相邻同文）"
            stats[key] = stats.get(key, 0) + 1
            continue
        out.append(Msg(role=m.role, text=text, ts_ms=m.ts_ms))
    return out
