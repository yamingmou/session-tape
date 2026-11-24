# 0.1.2

第七个产品 **OpenCode**，读写全通；读侧依赖归一。

## 新增

- **OpenCode 支持**（读 + 写）。实测基线：桌面客户端 2.2.7 / CLI 1.14.28。
  - 读：走 `session-fork-core` 的适配器层，与本项目同一套读法；
  - 写：只写新一代 `session_v2` + `session_message`（旧表在产品新建会话里本来就是 0 行），
    并补 `event_sequence` 发号器、沿用源会话的 `project_id`、用 `ses_` 形态的 id。
  - 验收用产品自己：`opencode session list` 列得出、`session export` 导得出且用户消息逐条一致。

## 改进

- **读侧统一依赖 `session-fork-core`**：装一个包即可读全部七个产品。
- **`--model`**：指定目标会话的模型（`providerID/model`，如 `ollama/qwen2.5:3b`）。
  默认继承模板会话的模型；若那个模型的免费额度用尽，产品侧会表现为"输入后一直工作中"，
  实际是 `idle{outcome:failed, error:provider.free-limit}`——本版会把这个风险打印出来。
- **落点自动回落**：目标目录在产品里还没出现过时，退到最近活跃的已知目录并明说，
  不再直接报错（装过/打开过产品就一定有默认项目）。

## 已知边界

- OpenCode 的**界面可见性**只在"产品自己列出/导出"这一层验过；分支（有 parent 的会话）
  不会出现在 `session list`（它只列 top-level），这是产品设计，不是缺陷。
- Claude Code / OpenClaw 两个目标仍只到"格式往返"（L1）。
- 迁移只搬对话文本：工具调用、附件、思考、模型身份都不搬。

## 升级

```sh
pip install -U session-tape
# 需要读产品会话时：
pip install -U "git+https://github.com/yamingmou/session-fork-core.git"
```
