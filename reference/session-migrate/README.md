# 上游参考：xhluca/session-migrate 的**格式与验收文档**（只取文档，不取代码）

来源：<https://github.com/xhluca/session-migrate>（PyPI 同名 `session-migrate`，v0.13.0）
许可：**MIT**（`LICENSE.upstream`）。取用日期 2026-11-23。

**为什么单独建这个目录**：它和我们撞行业、撞关键词，但**不撞源产品**——它覆盖 18 个终端，却**没有 WorkBuddy、没有 OpenClaw**（我们的主场）。所以它是"教科书"，不是"依赖"。

## 这里的文档值在哪

| 文件 | 为什么留 |
|---|---|
| `docs/*-format.md`（每家一份：hermes / omp / vibe / cursor / devin / mastracode / copilot / antigravity …） | 每家的写入 schema + **"哪个版本的真 CLI 接受过"** + **显式丢失项清单**（loss keys）。我们要加第 2、第 3 个写目标时，不用从零逆向 |
| `docs/additional-target-formats.md` | 目标格式的补充说明（含图片 blob 等边界） |
| `docs/specification.md` | 它的中间层设计（Event 7 种 + Provenance 可回溯） |
| `docs/credential-free-native-testing.md` | **最有价值的一份**：怎么在"没有真 key"的情况下用协议桩做过原生验收 |
| `docs/validation-report.md`、`docs/format-compatibility.md` | 逐家的验收结果与兼容性边界 |
| `docs/architecture.md` | 整体架构（hub-and-spoke） |

## 三方位置（2026-11-23 结论）

| 层 | 我们 | xhluca | agent-session-sync |
|---|---|---|---|
| 源覆盖 | 6 家**含 WorkBuddy / OpenClaw** | 18 家，**无 WorkBuddy / OpenClaw** | 18 家，含 WorkBuddy |
| 写侧质量 | 1 家（pi），**目标自读 + 真续跑已过** | **18 家，20 个真机 CI job** | 12 家，仅 dsh 过"目标自读" |
| 验收方法论 | 手工一条（ollama + 肉眼看续跑） | **自动化门禁**（空 HOME + 假 key + 协议桩 + 事后重解析 + 禁 skip） | 无 |

## 我们做过的两次交叉验证（这是收它的主要理由）

1. **它的解析器认我们的产物**：`session-migrate inspect` 读我们生成的 pi 文件 → `format: pi` / 30 条 / 26 assistant + 3 user / 文本块 29。
2. **同源转换结构完全一致**：同一条 Codex rollout，它的 `convert --to pi` 与我们 `session_tape` 的产物：条目数、消息数、角色、块类型、8 位 hex id、assistant 外壳键 **逐项相同**。
   **唯一差别**：它的 `provider/model/api` 带**源模型真实身份**（`openai` / `gpt-5.6-terra` / `openai-responses`），我们填的是占位 `migrated`。→ 待改（把源模型身份透传过去，比占位诚实）。

## 明确不做的三件事

1. **不依赖它**：它是 CLI 不是库（`__init__.py` 只有版本号），要用只能 subprocess；而且它的写侧**钉死具体 CLI 版本**（pi 0.80.6 / claude 2.1.209 / codex 0.144.4），版本一漂就废。
2. **不把 IR 加厚**：它有 7 类事件 + 工具调用 + 思考 + 压缩边界，代价是 20 个 CI job、每家钉版本、仍有一屏 `OPAQUE` 丢失。我们"只搬人说的话"是定位，不是缺陷。
3. **不叫 `smigrate`**：那是它的第二个 entry point，两家同时装会互相覆盖。我们的命令固定用 `session-tape`。

## ⚠️ 使用纪律

它的文档基线是 **2026-08～09 的版本**（`codex 0.144.4` / `pi 0.80.6` / `claude 2.1.209`）。
我们 11 月就撞上三处存储变更（Hermes 0.23 / OpenClaw 2026.11 / Codex 0.169）⇒ **里面的版本相关结论必须自己复核**。它自己的 `convert` 也当场报过 `source version differs from the pinned integration target: observed 0.150.0-alpha.8, validated 0.144.4`——这句话本身就是提醒。
