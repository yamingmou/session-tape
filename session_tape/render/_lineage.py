"""谱系摘除：迁移不该在目标产品里留下"我是某条会话的分支"的痕迹。

**为什么需要这个**：迁移的登记复用了 `session-fork-core` 的 `register_branch`——
那是给"打分支"用的，天然会写一条**谱系边**（新会话 → 源会话）。

迁移不是分支：容器用的是模板会话的列默认值，内容却是另一段历史。
留着这条边有两个实际后果：

1. **状态可能沿谱系传播**——若产品有"归档态沿谱系继承"的规则（实测见过的设计），
   模板会话被归档，我们的迁移产物就会被一起当成归档态；
2. **谱系视图会误导人**——`session-fork tree` 里会显示成"这条是从那条分出来的"。

⚠️ 还有一处容易漏：有些产品**两个地方都表示父子关系**（如 codex 的
`threads.attached_thread_parent_id` 与旁路谱系索引）。只断一处，等于没断。
本模块负责旁路谱系那一处；`attached_thread_parent_id` 由登记时显式置 `None` 保证。
"""
from __future__ import annotations


def detach(ad, new_id: str) -> bool:
    """把 `new_id` 从旁路谱系索引里摘掉（只摘这一条，不动别人的）。

    返回 True = 摘掉了；False = 这个适配器没有 JSON 谱系索引（或本来就没有该条）。
    """
    reader = getattr(ad, "_read_index", None)
    writer = getattr(ad, "_write_index", None)
    if not (callable(reader) and callable(writer)):
        return False
    data = reader() or {}
    branches = data.get("branches")
    if not isinstance(branches, list):
        return False
    kept = [b for b in branches if not (isinstance(b, dict) and b.get("id") == new_id)]
    if len(kept) == len(branches):
        return False
    data["branches"] = kept
    writer(data)
    return True
