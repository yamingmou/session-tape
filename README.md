# 迁移录音机（session-tape）

**把一个产品的会话历史，搬到另一个产品里继续。** 只搬人说的话和模型的回答——也就是**历史**；不搬工具调用、不搬附件、不搬状态。搬过去之后，新平台按它自己的方式往下走。

> **名字为什么不是 `session-migrate`**：2026-11-23 发现这个包名在 PyPI 上已被 [`xhluca/session-migrate`](https://github.com/xhluca/session-migrate) 占用（v0.13.0，183 star，覆盖 18 个终端 harness），GitHub 上同名仓库也是它。我们改叫 **`session-tape`**——正好对得上"录音机"这个比喻，且 PyPI 与 GitHub 都不冲突。

> 名字的来历：像录音机——**读 A 录的音 → 按 B 的磁带格式写一份 → 丢进 B 的机器 → 让 B 自己放**。
> 源只读一次，离线跑，不实时。

## 它不是什么

| 不是 | 因为 |
|---|---|
| **不是"打分支"** | 打分支是**同一个产品内**复制前缀（那是 [`session-fork`](https://github.com/yamingmou/session-fork-core) 做的事）；这里是**跨产品搬运**，两个产品一个命令都不共用 |
| 不是双向同步 | 单向：A → B。在 B 里继续聊之后想回 A，等于再做一次迁移 |
| 不是"迁移状态" | 不搬工具调用、思考过程、附件、工作区文件。这些每家都不一样，搬过去也没意义 |

## 它能做什么

```
读 A 的历史  →  规范成 (角色, 文本, 时间)  →  按 B 的格式生成  →  用 B 自己的解析器验收
```

**验收判断依据一律用目标产品自己**（它自己的解析器能不能读、能不能列出、能不能接着聊），不用我们自己的断言自证。

## 现在支持什么

| 方向 | 状态 |
|---|---|
| 源：WorkBuddy / Claude Code / Codex / Hermes / pi / OpenClaw | 复用 `session-fork-core` 的读侧（六个适配器都是真机验过的） |
| 目标：**pi** | ✅ 已跑通：真实 796 KB 会话搬过去，pi 自己读得下、能续跑、答对内容 |
| 目标：**workbuddy** | ✅ 隔离库副本上真写：转录 + `sessions` 行都对，能按 WorkBuddy 口径读回（3 user / 26 assistant） |
| 目标：**codex** | ✅ **用户真机验收通过**（2026-11-24 01:27）：迁移后的会话在客户端里能打开、**能继续对话、能继续执行任务**（截图里它已经在跑 `rg --files …` 这类命令） |

## 🎯 路线图：**任意平台 ↔ 任意平台**

目标不是"迁到 pi"，而是 **N×N**：任何受支持的产品都能迁到任何另一个（含同一产品换机器）。

我们已经是枢纽结构（`源 → Msg → 渲染器`），所以 **N×N 不需要 N² 条代码**，只需每个产品都具备两件东西：

| 能力 | 现状 |
|---|---|
| **读**（源） | 6 个产品 ✅（WorkBuddy / Claude Code / Codex / Hermes / pi / OpenClaw） |
| **写**（目标） | 3 个产品 ✅（pi / codex / **WorkBuddy**） |

已验过的组合（2026-11-24）：WorkBuddy→pi、WorkBuddy→codex（**用户真机**：能继续对话+执行任务）、
Codex→pi、Codex→WorkBuddy、pi→codex、以及**链式** WorkBuddy→pi→codex（29→29→29，时间保留源的真实日期）。
逐条证据与自验命令见 [`验收单.md`](验收单.md)。

每加一个"写"，矩阵多一整行；加到 6 个就自然闭环成 36 格。

**每个新目标必须回答三件事**（否则矩阵是假的）：

1. **容器怎么来** —— 文件型自己造头部；DB 型拿产品自己建的一条当模板；能"官方建壳"的优先用官方（见 codex 的 `--fill`）；
2. **怎么让产品看见** —— 只写文件不够（DB 型产品要登记一行），否则文件在、列表里没有；
3. **怎么验** —— 一律用**产品自己**：它自己的解析器 / 列表 / 续跑。我们自己的断言不算。

**顺序（按"能验 + 有人用"排）**

| 优先级 | 目标 | 为什么 | 关键难点 |
|---|---|---|---|
| 1 | **WorkBuddy** | 用户主力产品；fork 适配器已会写它的会话（分支写法），渲染器可复用那套知识 | SQLite 整行 + 4 个新列 + 项目归属 |
| 2 | Hermes | 本机装着（可真机验）；补 DB 写入的另一条路径 | 库结构版本白名单 30–33 |
| 3 | Claude Code | 用户面广 | JSONL + 树状 id（不是链） |
| 4 | OpenClaw | 我们主场 | 两代后端（JSONL / SQLite）、压缩事件 |
| 5 | pi / Codex 换机器 | "同产品跨机"也是迁移 | 路径与账号字段不能照搬 |


## 已经验证到什么程度（2026-11-23）

| 步骤 | 判断依据 | 结果 |
|---|---|---|
| 转 | 输出是 pi 的格式 | header v3 + 31 条消息 |
| **产品读** | pi 自己的 `loadEntriesFromFile` / `buildSessionContext` | 32 条目 / 上下文重建 31 条、顺序正确 |
| **产品写** | `pi --session <件> --print "…"` | exit 0 |
| **真续跑** | 会话文件是否被追加、id 链是否接上 | 31 → 35 行；新增 user+assistant；`parentId` 从我们生成的 id 续上 |

零密钥是怎么做到的：pi 支持在 `~/.pi/agent/models.json` 里接本机 ollama（`http://127.0.0.1:11434/v1` + `api: openai-completions`，并关掉 `supportsDeveloperRole`）。

## 用法

```sh
# 装（读源需要 session-fork-core 的适配器）
pip install "git+https://github.com/yamingmou/session-fork-core.git@v2.4.24"

# ① 搬到 pi（文件型）
python3 -m session_tape --from workbuddy --session <会话id> --to pi --out <pi 的 sessions 目录>

# ② 搬到 codex —— 推荐：先在界面上 fork 一条，拿到它的 id，再灌内容（官方建壳、我们灌内容）
python3 -m session_tape --from workbuddy --session <会话id> --to codex \
  --fill <界面 fork 出来的 id> --name "想显示的名字"

# ③ 搬到 codex —— 自己造壳 + 登记（没有官方壳时用）
python3 -m session_tape --from codex --session-file <某 rollout> --to codex \
  --install-codex-home ~/.codex --name "标题"

# ④ 搬到 workbuddy（建议先指到库副本，确认无误再写真实库）
python3 -m session_tape --from codex --session-file <某 rollout> --to workbuddy \
  --install-wb-home <含 workbuddy.db 与 projects/ 的目录> --name "标题" --cwd <真实目录>

# 通用开关：--session-file（源 id 有歧义时直指文件）、--limit N（只搬最后几轮）、--dry-run
```

### 验收（一律用产品自己）

```sh
# pi：解析器 + 自动化门禁（空 HOME + 本地协议桩，断言历史真进了上下文）
node lab/verify.mjs <pi 产物>
python3 scripts/verify_gate_pi.py --pi <pi 可执行文件> --session <pi 产物>
```

## 依赖

读侧复用 `session-fork-core`（MIT），作为外部依赖装，不复制代码：

```sh
pip install "git+https://github.com/yamingmou/session-fork-core.git@v2.4.24"
```

## 目录

```
session_tape/
  source.py      读源（调 fork_core 的 adapter）→ 规范化成 Msg
  noise.py       丢掉占位/中断文本、合并重复投递
  render/pi.py   生成 pi 的磁带（header + 线性 id 链）
  cli.py         命令行
lab/             旧原型（convert.py / verify.mjs），保留作对照
tests/           契约测试
```

## 边界（会写进对外说明）

1. **只搬文本**：工具调用、附件、思考过程不搬。所以搬过去的历史"读得通、能接着聊"，但**不能指望它在 B 里重放当初的工具动作**。
2. **单向**，且不保证 A 里的会话编码/元数据在 B 里都有对应物（缺的用占位值或目标默认值）。
3. 源只读：迁移过程不修改源产品任何文件。

## 已知问题 / 待办

- ~~Codex 的会话 id 是"线程级"的，跨多次运行共用~~ **已补 `--session-file <路径>`**：直接指定某个 rollout 文件，绕开按 id 找。`--session` 与 `--session-file` 必须且只能给一个。
- 目标产品：**pi**（文件型）+ **codex**（文件 + `threads` 行；推荐用 `--fill`）。第三个待定。
- 规范化只保留 `(角色, 文本, 时间)`：源里的"工具调用顺序"这类信息会丢，属刻意取舍。
- `--session-file` 模式下输出里的"源会话 id"为空（文件里没有可靠的 id 字段），属显示问题。

## 路线图：目标是**任意平台互相迁移**

方向定了：不是"给每个产品写一条专用路"，而是**一个薄中间层 + 每个产品一个写侧**。
这样 N 个源 × M 个目标只需要 **M 个写侧**，而不是 N×M 条路。

```
        源（读侧，复用 session-fork-core 的适配器）
   workbuddy · claude-code · codex · hermes · pi · openclaw
                          ↓  规范化成 (角色, 文本, 时间)
                    ┌──────────────┐
                    │  薄中间层     │  ← 只有三样东西：不搬工具/附件/思考
                    └──────────────┘
                          ↓  每个产品一个写侧
              pi（文件） · codex（文件+库） · …（待补）
```

| 阶段 | 目标 | 判断依据 | 状态 |
|---|---|---|---|
| **P0** | 两条写侧闭合（pi / codex）+ 验收门禁 | 目标产品自己的解析器能读；codex 用 `--fill` 时 id/元数据不变 | ✅ 已完成 |
| **P1** | **矩阵打通**：源 × 目标 的组合逐个跑一遍 | 每个组合都由目标产品自己读回；不支持的组合**明确拒绝**（附替代做法） | 🚧 在做 |
| **P2** | 第三个、第四个写侧 | 同上；优先选"库型"产品（Hermes 本机有、且是 SQLite 行写入） | 待做 |
| **P3** | **任意平台互迁**：支持表内任意组合自动可用 | 支持表 = 读侧 6 × 写侧 K，矩阵全绿；每个组合在 README 里标注已知丢失 | 待做 |
| **P4** | 兜底：目标不在支持表内 | 退化为**接力消息**（把上下文压成一条可粘进新对话的消息），保证"任何方向至少有路" | 待做 |

**两条硬纪律**（P1 起适用）：

1. **同一产品互迁要拒绝并指路**：`--from codex --to codex` 不是迁移，是打分支 ⇒ 直接报错并提示用 `session-fork`；
2. **每个组合都要有"目标自己读"的证据**，不接受"结构看起来对"。矩阵跑不了真机时（例如本机没装那个产品），必须在表里标成**未验**，不能算绿。

