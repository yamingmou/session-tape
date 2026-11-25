# 验证记录 · session-tape

> 只写**能自己复核**的东西。每条都给了命令，可自行重跑。
> 判断依据一律是"**目标产品自己**认不认"，不是"我们自己断言它对"。

## 一、能力矩阵（谁 → 谁）

| 方向 | 状态 | 怎么验的 |
|---|---|---|
| WorkBuddy → **pi** | ✅ | pi 自己的解析器 + **自动化门禁**（协议桩，四条断言） |
| WorkBuddy → **codex** | ✅ | **真机验收**：产品自己打开后能继续对话、能执行任务 |
| **Codex** → pi | ✅ | pi 解析器 + 真续跑（答对内容） |
| Codex → **WorkBuddy** | ✅ | 隔离库副本上写 + 用 WorkBuddy 口径读回（3 user / 26 assistant） |
| **pi** → codex | ✅ | 链式第 2 跳，29 条原样过去 |
| WorkBuddy → pi → codex（**链式**） | ✅ | 29 → 29 → 29，时间保留源的真实日期 |
| WorkBuddy → WorkBuddy（换目录） | ✅ | 隔离库副本；cwd 已按指定目录改写 |

**还没做**：Claude Code / Hermes / OpenClaw 作为**目标**（作为源已可用）。

## 二、每个目标的"三件事"（新加目标必须回答的）

| 目标 | ① 容器怎么来 | ② 怎么让产品看见 | ③ 怎么验 |
|---|---|---|---|
| **pi** | 自己造 header（版本 3 + 8 位 hex id 链） | 文件型：放进 `~/.pi/agent/sessions/<cwd>/` 即可 | 它的 `loadEntriesFromFile` / `buildSessionContext` + 真续跑 |
| **codex** | 两种：**自己造**（模板行登记）／**官方建壳 + `--fill`**（推荐） | 必须补 `state_5.sqlite` 的 `threads` 一行 + 投影归零 | 它认得会话（resume 时报的是 provider 冲突，不是 not found）；你点运行 |
| **workbuddy** | 自己造（id 链 + 毫秒时间戳） | 文件 + `sessions` 表一行 | 用 WorkBuddy 口径读回 + 库行字段核对 |

## 三、最快的一条：自检

```sh
FORK_CORE_PATH=<fork 仓库路径> python3 scripts/selfcheck.py --pi <pi 可执行文件>
```

它会打印一张 7 行的表：4 份契约测试、噪声过滤、三个目标的往返（渲染→落盘→**用产品口径读回**）、
链式 WB→读回→codex、以及 pi 的真机门禁。**退出码 0 = 全过**。
（不给 `--pi` 就跳过真机门禁那行。）

实测输出（2026-11-24）：

```
契约测试（4 份）       ✅    test_codex_render.py✓ test_noise.py✓ test_pi_render.py✓ test_workbuddy_render.py✓
噪声过滤              ✅    丢 {'占位/中断文本': 1, '重复投递（相邻同文）': 1}
pi 往返               ✅    4 条往返一致
codex 往返            ✅    4 条往返一致；落盘 rollout-2023-11-14T22-13-21-…
workbuddy 往返        ✅    4 条往返一致；项目目录 tmp-proj
链式 WB→读回→codex    ✅    WB → 读回 → codex，4 条一致
pi 真机门禁           ✅    门禁四条断言全过
```

## 四、逐条命令（想单独跑某一项时用）

```sh
SK=<本仓库路径>
export FORK_CORE_PATH=<session-fork-core 的本地检出路径>

# 1) 全部契约测试（4 个，纯断言，不需要任何产品在场）
for t in $SK/tests/test_*.py; do python3 "$t" || echo "FAIL $t"; done

# 2) 从 WorkBuddy 搬到 pi（产物 + 用产品自己的读法验收）
python3 -m session_tape --from workbuddy --session <会话id> --to pi --out /tmp/pi-out
node $SK/lab/verify.mjs $(ls -t /tmp/pi-out/*.jsonl | head -1)

# 3) pi 的自动化门禁（空 HOME + 协议桩，断言历史真的进了上下文）
python3 $SK/scripts/verify_gate_pi.py --pi /path/to/pi --session <上面那个文件>

# 4) 搬到 codex（官方建壳 + 灌内容：先在界面 fork 一条，拿它的 id）
python3 -m session_tape --from workbuddy --session <会话id> --to codex \
  --fill <界面 fork 出来的 id> --name "想显示的名字"

# 5) 搬到 codex（自己造壳 + 登记）
python3 -m session_tape --from codex --session-file <某 rollout> --to codex \
  --install-codex-home ~/.codex --name "标题"

# 6) 搬到 WorkBuddy（先指到隔离副本，别写真实库）
cp ~/.workbuddy/workbuddy.db /tmp/wbtest/workbuddy.db
python3 -m session_tape --from codex --session-file <某 rollout> --to workbuddy \
  --install-wb-home /tmp/wbtest --name "标题" --cwd /tmp/某个真实目录
```

## 五、能力边界（会写进对外说明）

1. **只搬文本历史**：工具调用、附件、思考过程、模型身份都不搬。所以搬过去"读得通、能接着聊"，但**不能指望它在 B 里重放当初的工具动作**。
2. **单向**，且不保证源里的编码在目标里都有对应物（缺的用模板/默认值补）。
3. **源只读**：迁移过程不改源产品任何文件。
4. **DB 型目标需要登记**：只写文件，产品列表里看不见。

## 六、这一版修掉的坑（每条都是真机撞出来的）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | 列表里多出几条一模一样的会话 | 复用 fork 的注册逻辑：模板的"第一句"被复制过来（fork 时正好对，迁移时错） | 覆盖 `first_user_message` / `preview` |
| 2 | 隔离测试写进了真实库 | `CODEX_HOME` 在适配器 `__init__` 里读，设晚了 | 构造前设，`finally` 还原 |
| 3 | `--limit 3` 切出"没有人类提问"的会话 | 截取方向错（往后丢） | 向前扩到最近的 user 起点；空切片报错 |
| 4 | pi 打不开会话 | 源里的 cwd 在本机不存在 | 用户指定的就建出来；源推导的就回退并明说 |
| 5 | 链式迁移目录落到 `1970/01/01` | pi/Claude 的时间戳是 ISO 字符串，只认数字会读成 0 | 支持 ISO 解析；整段无时间时退回"现在" |
| 6 | workbuddy 会话的项目目录与 cwd 不一致 | 项目目录写死、cwd 被模板带过来 | 目录按 cwd 推导 + 覆盖 cwd |


## 七、一条诚实的边界：我们无法断言"产品可见"

写文件 ≠ 产品看得见。codex 是两件套（rollout 文件 + `threads` 一行），
workbuddy 也是（转录 + `sessions` 一行），少一行就"文件在、列表里没有"。

但"出现在列表里"这件事**不一定**能自动断言——那要跑产品自己的索引逻辑。
所以 codex 侧我们只断言一条**能读的代理指标**：

> **消费进度必须是初始值 `(0,0)`**（`thread_history_1.sqlite` 的 `thread_history_projection_state`）

产品记着"这条 rollout 我消费到第 N 字节"。若 N>0，新写的内容永远不会被解析，界面就是空的或旧内容。
所以：**代理指标通过 ≠ 产品可见；但它失败就一定看不见。**

代码位置：`session_tape/render/codex.py::_assert_projection_zero`，登记与灌内容之后都会跑，
失败就报错并说明该把哪两个字段归零。测试见 `tests/test_codex_projection.py`。

## 八、OpenCode：**读通过、写通过（L3）**

**基线**：OpenCode 桌面客户端 2.2.7（`/Applications/OpenCode.app`，内含 `opencode-cli` 2.2.7）。

| 项 | 状态 |
|---|---|
| 读（作为源） | ✅ 真实库可读；已跑通 **OpenCode→pi** |
| 写（作为目标） | ✅ **L3**：`opencode session list` 列得出来，`session export` 导得出且用户消息逐条一致 |
| 已跑通 | ✅ **WorkBuddy→OpenCode**（29 条，产品侧验收通过） |

### 怎么攻下来的（试出来的，不是设计出来的）

前两次都失败：手写两代库表 → 产品列不出来；官方 `session import` → 对新会话一律 `Bad Request`。
转折点是**拿产品自己建的会话当基准**（在客户端里新建一条，再逐字段 diff），由此得到四个事实：

1. **新版只写 `session_v2` + `session_message`**，`session` 表里 0 行；
2. **必须有 `project` 行**，否则 `session list` 空（它按目录→项目过滤）；
3. **`project.id` 算不出来**：13 个已知行、7 种哈希变体（sha1/sha256/blake2b/md5/加斜杠/realpath/加前缀）**0 命中**
   ⇒ 是产品创建时生成的随机 id。而且 **`project` 行只有产品自己会建**（在客户端里打开该目录/在那里建会话时），
   我们试过三种"借产品的手"（`session list` / 原样 import / 改 id 后再 import）都不建。
   ⇒ **写入的目录必须是客户端已认可的目录**；`--to opencode` 会列出可用目录并明说要先在客户端里打开一次。
4. **消息 data 的真实形状**：user 带 `metadata.displayText/agent/model`；assistant 带 `content` 块
   与 `time.streamed/completed/finish/tokens`；末尾要有 `idle` 消息。
   而且 **assistant 在 `export` 里 `text` 本来就是 `None`**（真基准也这样），不是我们的 bug。

### 三个"看起来像迁移坏了、其实不是"的现象（都实测过）

| 现象 | 真因 | 判据 |
|---|---|---|
| 历史看得见，输入新消息**一直转圈（工作中）** | 缺 `event_sequence(aggregate_id, seq)` 发号行 ⇒ 产品从低位发号，撞上已有序号 | 真实会话的发号器**总 ≥ 已用最大 seq**（实测差 0~34）；补 `max+1` 即恢复 |
| 同上 | 继承的模型**免费额度用尽** ⇒ 写一条 `idle{outcome:failed, error:provider.free-limit}` | 查 `session_message` 里最后那条 `idle` 的 `error.type`，一眼可辨 |
| 回复**空白但成功** | 小模型（如 3B）在长上下文下只吐几个 token，没形成内容块 | `tokens.output` 有值而 `content` 为空 ⇒ 是模型侧，不是迁移侧 |

⭐ 第二条是用户实测的：切到本地 `ollama/qwen2.5:3b` 之后同样的会话**两次都 succeeded**，
而且 `tokens.input = 10255` / `cache.read = 10257` —— **我们迁的历史确实进了模型上下文**，
这是"迁移真的成立"最直接的证据。

### 落点：默认项目总是存在，所以"总能迁"

`project` 行只有产品会建，但这不构成阻塞——**装过/打开过 OpenCode 就至少有一个默认项目**。
所以 `--cwd` 指向客户端不认识的目录时，工具**自动退到最近活跃的已知目录**并明说退到了哪；
想落在别处就在客户端里打开那个目录一次。

### 另一个坑（值得记住）

**opencode CLI 不认 `XDG_DATA_HOME`** —— 它永远读 `~/.local/share/opencode/opencode.db`。
我一开始用"副本库 + 临时 XDG"做隔离测试，结果测试数据全写进了真实库（还留下 9 条临时 project 行，已清理）。
⇒ 所以产品验收在测试里**默认跳过**，要用 `SESSION_TAPE_PRODUCT_CHECK=1` 显式开启。

## 九、还没做的（明确列出，不含糊）

- **OpenCode 的写**：官方 import 的 JSON 校验未攻克（读已可用）；
- 目标产品还差 **cursor / kimi / qwen / gemini / cline / kilo**；
- **多源批量**：现在一次一条会话，没有"整库搬家"；
- **同产品跨机**：路径/账号字段还不能自动改写（`/Users/A/…` → `/home/B/…`）；
- **L1 那两家的界面可见**：claude-code / openclaw 只到格式往返。

## 十、Qwen（QwenWorkCN，第八个产品）· 写 = **L3**

**基线**：QwenWorkCN 桌面端，库在 `~/Library/Application Support/QwenWorkCN/data/agents.db`
（实测 11 会话 / 356 条消息）。

| 项 | 状态 |
|---|---|
| 读（作为源） | ✅ 真库可读（有一条 166 条的会话读通） |
| 写（作为目标） | ✅ **L2**：库副本写入、我方读器读回逐条一致；原会话未动 |
| 界面可见 | ✅ **已验**（2026-11-25 用户在 QwenWorkCN 会话列表里看到「Qwen 分支验证」） |

### 三件必须照做的事实

1. **`searchable_text` 是搜索的承载点**：FTS 触发器直接把它塞进 `messages_fts`
   （`AFTER INSERT … VALUES (NEW.searchable_text, …)`）。不填它，消息在界面上有、**但搜不到**
   ——又一个"两个地方都要写、只写一处等于没写"。（这一条与 opencode 的 `event_sequence`
   是同族：产品把"能不能用"分散在多个承载点上。）
2. **时间戳按秒**（`1793805524`），写毫秒会被显示成几万年后。
3. **三张表都要有行**：`chats` + `sub_chats` + `messages`；`chats.project_id` 为 NOT NULL
   且指向 `projects` 表，写入沿用模板会话的 `project_id`（自造没有依据）。

### 顺手修掉一个我自己写的边界 bug

时间戳单调性修正里 `prev` 初始值取成"首条时间戳"，导致**首条被顶高 1 秒**
（qwen 与 opencode 两处同款）。改成 `first - 1`，测试里直接断言首条时间戳等于原值。

## 十一、明确**不支持**的产品（带判据，免得有人白试）

三个产品在本机装着，但都做不了。**判死的理由各不相同**，写在这里比写"暂不支持"有用：

| 产品 | 判据（实测） | 结论 |
|---|---|---|
| **Trae CN** | `ModularData/ai-agent/database.db`（80 MB）与 `ckg_server/env_codekg.db` 的文件头**都不是** `SQLite format 3`；前 96 字节 32/32 位互不相同（高熵）⇒ 加密或私有格式 | ❌ 读不了：没有密钥 |
| **Windsurf** | 会话索引 `chat.ChatSessionStore.index` 的值是 `{"version":1,"entries":{}}` —— **global 与 7 个 workspace 里全为空** | ❌ 本地无转录：Cascade 会话在云端 |
| **Kimi** | `~/Library/Application Support/Kimi` 只有 4 KB | ⚪ 不是不支持，是**无样本**（装了没用过） |

⚠️ 这三条都是**否证**，不是猜测：`database.db` 那种"看着像 SQLite 但打不开"的情况，
最容易被误判成"驱动问题"而反复重试——所以把字节级判据写进来。

### 如果要支持它们，前置条件是什么

- Trae：需要它的加密方案与密钥来源（客户端里取，属另一件事）；
- Windsurf：需要它的云端 API 或导出功能（不是本地文件问题）；
- Kimi：先在客户端里真用一轮，再谈格式。
