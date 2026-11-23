# 上游参考：agent-session-sync 的**格式知识库**（只取文档，不取代码）

来源：<https://github.com/Chendestiny/agent-session-sync>（`SKILL.md` 自报 v1.2.0）
许可：**MIT**（见 `LICENSE.upstream`；上游在许可证末尾追加了一段中文 attribution，声明 dsh 事件合成纪律移植自 `Nwflower/dsh-chat-import`，WorkBuddy 规格参考 `westsource/agentctxsync`，那两处也是 MIT）。保留原许可与出处即可。

取用日期：2026-11-23。取的是当时的快照，**上游后续更新不会自动进来**。

## 这里有什么

| 文件 | 是什么 | 为什么留着 |
|---|---|---|
| `FORMATS.md` | 各产品会话格式的总览 | 换目标产品时先看它，比我们从零摸快 |
| `agents/*.md` | **20 份单产品分册**（claude / codex / workbuddy / hermes / pi / openclaw / dsh / opencode / cursor / trae / qoder / cline / gemini / kimi / kilo / minimax / mimo / zcode / grok / copilot） | 这是它最值钱的部分：**被人踩过的字段与坑**，很多是我们还没遇到的 |
| `pitfalls.md` | 62 条踩坑记录（18 KB） | 同上。含 opencode 六层 schema 报错原文、codex `state_5.sqlite` 索引、zcode 报废全过程 |

## 为什么只取文档，不取代码（结论来自 2026-11-23 的一轮调研）

| 判断依据 | 它的情况 | 我们的情况 |
|---|---|---|
| **写侧是否经过"目标产品自己读一遍"** | **只有 dsh 一家过了**（且给了可复跑脚本）；其余 11 家是作者本机 UI 肉眼验收；**pi 作者自认没验到** | 我们只有 pi 一个目标，但是**用 pi 自己的解析器 + 真续跑**验的 |
| 平台基线 | Windows（19 家里 macOS 只能探测到 5 家，路径逻辑写死 `%APPDATA%`） | 我们的 6 家都在 macOS 真机验过 |
| 工程成熟度 | 5 star、无 CI、无 tests/fixtures、单作者、68 天未提交 | — |
| 分发形态 | 不是 pip/npm 包（无 `pyproject.toml`），只能 vendor | 我们是标准 Python 包 |

⇒ **不依赖它、不替换我们的读侧、不装它的 Skill**（它的 `install.sh` 会往各家 skills 目录建软链并注册全局命令）。

**一个反例值得记**：它的 `piwrite.py` 生成的会话文件名是 `…+00-00_<uuid>.jsonl`，而它**自己的真机记录**写的是 `…-717Z_<uuid>.jsonl`——它的实现对不上它自己的文档；我们 `render/pi.py` 用的是后者（与真机一致）。**说明"顺着别人的代码抄"不如"照产品的真机事实写"。**

## 使用建议

1. 要加新目标产品时，**先读 `agents/<产品>.md` + `pitfalls.md` 里对应条目**，再动手；
2. 里面的结论**必须自己复核**——它的基线是 2026-08～09 的版本，而各产品改得很快（我们 11 月就撞上 Hermes 0.23 / OpenClaw 2026.11 / Codex 0.169 三处存储变更）；
3. 若哪天要 vendor 它的某个 writer：可以，依赖极浅（单文件 + stdlib），但**vendor 后由我们接管**，不要当上游依赖——它 68 天没提交了。
