#!/usr/bin/env python3
"""噪声过滤的契约测试（纯断言，不依赖 pytest）。

三条判断依据都来自真数据：占位文本、平台包裹、重复投递。
每条都带一个"不该被动到"的负向用例——只测"能过滤"不够，
还得证明它没顺手把正常对话也吃掉了。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_tape.model import Msg          # noqa: E402
from session_tape import noise              # noqa: E402

# 1. 占位/中断文本
assert noise.is_placeholder("Interrupted by user") is True
assert noise.is_placeholder("[Request interrupted by user]") is True
assert noise.is_placeholder("  [Request interrupted by user for tool use]  ") is True
assert noise.is_placeholder("No response requested.") is True
assert noise.is_placeholder("") is True
assert noise.is_placeholder("   ") is True
# 负向：正常话不能被当成占位
assert noise.is_placeholder("继续") is False
assert noise.is_placeholder("帮我看看这个中断日志") is False
assert noise.is_placeholder("Interrupted by user 之后我怎么恢复？") is False
print("✓ 占位判定（含负向）")

# 2. 平台包裹
wrapped = ("<system-reminder>\n当前工作区是 X\n</system-reminder>\n"
           "<user_query>把这段代码解释一下</user_query>")
assert noise.strip_wrappers(wrapped) == "把这段代码解释一下"
nested = "<system-reminder>外层 <user_query>内层真正的指令</user_query> 尾巴</system-reminder>"
assert noise.strip_wrappers(nested) == "内层真正的指令"
# 负向：没有包裹的正文原样返回（首尾空白除外）
assert noise.strip_wrappers("  普通的一句话  ") == "普通的一句话"
# 负向：正文里出现尖括号但整条不是包裹形态 ⇒ 不动
inline = "我写了 <div>x</div> 这样一行 HTML"
assert noise.strip_wrappers(inline) == inline
print("✓ 包裹剥离（含负向）")

# 3. clean：过滤 + 合并重复 + 计数
#    真实形态：用户连发同一条（相邻）⇒ 合并；占位夹在中间 ⇒ 丢弃；
#    但"同一句话隔着一轮又问一次"⇒ **不能**合并（那是两轮不同的对话）。
msgs = [
    Msg("user", "<user_query>第一问</user_query>", 1),
    Msg("user", "第一问", 2),                        # 连发 ⇒ 与上一条同文，合并
    Msg("assistant", "第一答", 3),
    Msg("assistant", "Interrupted by user", 4),      # 占位 ⇒ 丢
    Msg("user", "第二问", 5),
    Msg("assistant", "第二答", 6),
    Msg("user", "第一问", 7),                        # 隔了一轮再问 ⇒ 保留（不是重复投递）
]
stats = {}
out = noise.clean(msgs, stats)
assert [m.text for m in out] == ["第一问", "第一答", "第二问", "第二答", "第一问"], \
    [m.text for m in out]
assert stats.get("占位/中断文本") == 1, stats
assert stats.get("重复投递（相邻同文）") == 1, stats
print(f"✓ clean：留 {len(out)} 条，丢 {stats}")

# 4. clean 之后时间戳与角色保持不变（不能顺手改语义）
assert all(isinstance(m.ts_ms, int) for m in out)
assert [m.role for m in out] == ["user", "assistant", "user", "assistant", "user"]
print("✓ clean 不改角色与时间戳")

print("\n✅ noise 全部通过")
