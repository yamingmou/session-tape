"""规范化模型：迁移只认三样东西 —— 角色、文本、时间。

为什么只有这三样：
  六种产品的存储格式各不相同（JSONL / SQLite / LevelDB），但**人说的话和模型的回答**
  在每一种里都存在，而且顺序一致。工具调用、思考过程、附件则各家互不相通——
  搬过去也没有对应物，所以**不进模型**。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Msg:
    """一条可搬的消息。`role` 只会是 "user" 或 "assistant"。"""

    role: str
    text: str
    ts_ms: int = 0          # 毫秒时间戳；源里没有就留 0，渲染时按顺序补


@dataclass
class Source:
    """一次读源的结果：消息序列 + 一点随行信息。"""

    msgs: list[Msg]
    product: str = ""       # 源产品名（workbuddy / claude-code / ...）
    session_id: str = ""
    cwd: str = ""
    dropped: dict[str, int] = field(default_factory=dict)   # 各原因丢了多少条（给用户看）

    def __len__(self) -> int:
        return len(self.msgs)
