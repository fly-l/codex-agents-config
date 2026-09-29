# Codex、Claude Code 与 Pi 配置

一套共用的项目长期记忆 Skills、生命周期 Hook 和多代理协作规则。安装流程统一，主指令入口与 Hook 接入方式按宿主区分。

## 统一安装

先安装 Python 和目标宿主，在仓库根目录选择对应命令：

| 宿主 | 预览安装 | 实际安装 |
| --- | --- | --- |
| Codex | `python install.py --host codex` | `python install.py --host codex --apply` |
| Claude Code | `python install.py --host claude` | `python install.py --host claude --apply` |
| Pi | `python install.py --host pi` | `python install.py --host pi --apply` |

默认只预览，`--apply` 才安装主指令、同目录的 `SUBAGENTS.md`、两个项目记忆 Skills 和对应 Hook。可用 `--home <目录>` 指定宿主目录；这不是项目级安装开关，项目级目录布局见下方宿主说明。

| 宿主 | 宿主目录环境变量 | 默认目录 | 主指令源文件 → 安装文件 | Hook 目标 |
| --- | --- | --- | --- | --- |
| Codex | `CODEX_HOME` | `~/.codex` | `AGENTS.md` → `AGENTS.md` | `hooks.json` |
| Claude Code | `CLAUDE_CONFIG_DIR` | `~/.claude` | `CLAUDE.md` → `CLAUDE.md` | `settings.json` |
| Pi | `PI_CODING_AGENT_DIR` | `~/.pi/agent` | `PI.AGENTS.md` → `AGENTS.md` | `extensions/project-memory-hook.ts` |

已有主指令或 `SUBAGENTS.md` 与仓库不同则停止，不执行后续安装。请备份并人工合并，再分别使用下方 Skill 同步与 Hook 安装命令更新其他组件。Skill 和 Hook 的备份沿用各自安装器。Hook 引用本仓库绝对路径，安装后请保留仓库目录。

模型、API Key、Vault 路径和项目知识体系开关不自动配置；Codex 还需启用 `[features] hooks = true`。手动安装主指令时，必须同时复制 `SUBAGENTS.md` 到同一目录，该文件由主指令明确要求读取。

## 直接让 Agent 安装

把下面整段发给目标宿主的 Agent：

```text
请在当前环境中安装并初始化以下配置仓库：
https://github.com/fly-l/codex-agents-config.git

1. 阅读 README.md、当前宿主对应的主指令、SUBAGENTS.md 与安装脚本。确认目标宿主和安装范围；无法从上下文确定时再询问。
2. 检查已有指令、Skills、Hook 和模型配置。修改前备份，保留已有内容；统一安装器遇到指令冲突时，先人工合并，再分组件安装，不覆盖用户规则。
3. 用户级配置使用 python install.py --host <codex|claude|pi> 预览，再加 --apply 执行。项目级配置按 README 的宿主说明安装，主指令与 SUBAGENTS.md 放在同一目录。
4. Vault 统一使用 PROJECT_MEMORY_VAULT。启用项目记忆前确认项目名称、Vault 根目录、是否自动加载和自动收集，不猜测路径。按 project-memory Skill 填充有来源、已验证的首批记录，更新当前状态并校验；只创建空目录不算初始化完成。
5. 不擅自切换模型或写入 API Key。Codex 检查 hooks 开关；Claude Code 重启后检查 /memory、/skills 和 /hooks；Pi 重启或 /reload 后检查 Skill 与扩展。
6. 报告安装位置、备份、修改、实际验证结果与待手动完成事项。用真实会话验证 Hook，不把配置文件存在当作已经生效。
```

## 配置内容

```text
.
├── README.md
├── install.py
├── AGENTS.md
├── CLAUDE.md
├── PI.AGENTS.md
├── SUBAGENTS.md
├── Skills/
│   ├── project-memory/
│   └── project-memory-maintenance/
├── Hook/
│   ├── install.py
│   ├── install_claude.py
│   ├── install_pi.py
│   ├── manage_installation.py
│   ├── hooks.json
│   ├── project_memory_common.py
│   ├── project_memory_session_start.py
│   ├── project_memory_session_end.py
│   ├── conversation_title_session_end.py
│   ├── conversation_title_worker.py
│   └── pi/project_memory_hook.ts
└── tests/
```

多代理职责、委派条件、写入所有权、验收和宿主模型配置统一见 [SUBAGENTS.md](SUBAGENTS.md)。指令文件不能自行切换运行时模型，安装后仍需核实实际使用的模型。

## 项目记忆配置

在项目级指令文件中增加以下章节：Codex 与 Pi 使用 `AGENTS.md`（有 `AGENTS.override.md` 时优先），Claude Code 使用 `CLAUDE.md`。

```markdown
## 知识体系
- 启用：是
- 项目名称：示例项目
- 自动加载：否
- 自动收集：是
- 自动审核：否
```

`自动加载：否` 保持按需召回；设置为 `是` 时，SessionStart 才注入短 `当前状态.md`。`自动收集：是` 只登记待审核元数据。可按项目另开 `自动审核：是`：SessionStart 提示待审核元数据，由当前主代理在相关任务中限量核实并落盘；它不启动后台模型，也不自动把聊天当作事实。没有新会话或任务执行时，候选不会自行审核。

审核提示默认最多 1,200 字符，包含在 SessionStart 默认 4,000 字符的总预算内。可分别用 `CODEX_MEMORY_REVIEW_CHARS`、`CLAUDE_MEMORY_REVIEW_CHARS`、`PI_MEMORY_REVIEW_CHARS` 调整审核提示预算。每会话先审核最多 1 条相关候选，明确要求整理时再扩批；缺证据保留 `pending`，完成复核与校验后才标记 `processed`。

## 上下文与召回策略

| 场景 | 入口 | 成本与准确性控制 |
| --- | --- | --- |
| 具体问题 | `memory_store.py search --module <模块> --query "关键词"` | 默认 3 条、完整 JSON 最多 6,000 字符；精确 ID、关键词覆盖率优先，预览展示命中附近正文 |
| 关键词过宽 | 追加 `--match all` | 必须匹配所有词；默认 `any` 保留较宽召回，未命中时补查别名与源码 |
| 查看下一页 | `--offset <next_offset> --expected-snapshot <snapshot>` | 范围或正文变化时拒绝沿用旧页，重新查询，避免无声漏项 |
| 模块全貌 | `maintenance-audit --summary-only --module <模块>` | 仅返回摘要可用性，不加载维护候选；摘要不能证明源码仍然有效 |
| 完整维护 | `project-memory-maintenance` Skill | 按需加载详细流程，分批复核；普通召回不顺带扫描和总结整库 |

固定指令只保留启用条件和必要边界；初始化、写入及审核细节按当前任务加载。正文预览只用于定位，实现前仍需核实原文、仓库与版本。更新记录不会自动刷新已有 `verified_at`，完成复核后才显式传 `--verified-at`。

上述预算按字符计算，不是 token 或账单额度。是否需要语义检索，应先收集真实任务的漏召回案例；当前采用可解释的关键词召回，不引入嵌入模型、向量数据库或每轮总结调用。

所有宿主统一优先读取 `PROJECT_MEMORY_VAULT`，其次读取项目配置的 `Vault根目录`。两者都缺失时停止记忆操作，不猜测路径。

```powershell
$env:PROJECT_MEMORY_VAULT = "<Vault根目录>"
```

```bash
export PROJECT_MEMORY_VAULT="<Vault根目录>"
```

以上仅设置当前终端及其子进程的环境变量。需要长期使用时，在本机持久化后重启宿主；个人路径不要提交到公开仓库。旧的 `CODEX_MEMORY_VAULT`、`CLAUDE_MEMORY_VAULT`、`PI_MEMORY_VAULT` 不再读取，请迁移到新变量。独立脚本显式传入 `--vault-root` 时以命令行值为准。

## Skills 同步与更新

把 `<宿主>` 替换为 `codex`、`claude` 或 `pi`：

```bash
python Hook/manage_installation.py status --host <宿主>
python Hook/manage_installation.py sync --host <宿主>
python Hook/manage_installation.py sync --host <宿主> --apply
```

`status` 报告文件差异、依赖与 Hook 路径；`sync` 默认预览，`--apply` 才写入两个 Skill。每次实际同步在宿主目录的 `backups/codex-agents-config/` 下创建独立备份与哈希清单，保留仓库未管理的文件，不复制 `__pycache__` 或 `.pyc`。可用 `--home <目录>` 指定宿主目录。此命令不修改主指令、模型配置或 Hook 配置。

手动安装时必须复制完整 Skill 目录，包括 `SKILL.md`、`references/`、`scripts/` 和其他随附文件。

## 宿主差异

### Codex

主指令默认安装到 `~/.codex/AGENTS.md`，项目级规则放在项目根目录。已有 `[features]` 时合并以下字段，不重复创建表或覆盖其他配置：

```toml
[features]
hooks = true
```

单独预览或更新 Hook：

```bash
python Hook/install.py --dry-run
python Hook/install.py
```

安装器将 SessionStart 和 Stop 合并到 `hooks.json`，迁移旧 SessionEnd 中的受管处理器，保留其他处理器和元数据，覆盖前创建 `.bak`。重启后运行 `/hooks` 审核并信任新增 Hook。`Hook/hooks.json` 是通过 `CODEX_AGENTS_CONFIG_ROOT` 定位仓库的便携模板，安装脚本则生成绝对路径。

Codex 可通过 `$project-memory` 和 `$project-memory-maintenance` 调用 Skills。标题整理只在 Codex Desktop 中启用：

- 后台脚本先用 `read_thread` 核实目标线程 ID、标题和 `createdAt`；仅未整理时启动一次性 Luna 子代理读取内容并整理。
- 已符合 `MMDD｜类型｜主题` 且日期与 `createdAt`（Asia/Shanghai）一致时直接跳过。
- 只有主题可靠可判定时才调用 `set_thread_title`；无法判定就保留原名。
- 只允许修改当前对话标题，不修改项目名称、项目归属、内容、排序、置顶或归档状态。
- 子代理默认使用 `gpt-5.6-luna`（可用 `CODEX_RENAME_CURRENT_TITLE_MODEL` 覆盖），使用只读沙箱，仅暴露 `read_thread` 和 `set_thread_title` 两个 MCP 工具并自动批准。执行后重新读取验证标题；Stop Hook 返回 `{}`，不等待模型。
- 状态日志位于 `$CODEX_HOME/logs/conversation-title/`，可由 `CODEX_RENAME_CURRENT_TITLE_LOG` 指定目录。日志区分依赖缺失、启动失败、已整理、模型失败/超时、未修改和核验通过，不保存聊天正文或工具原始响应。

标题子代理依赖当前 Codex Desktop 提供的 `codex-app-tools` MCP 通道；不在桌面环境或找不到已安装的 `rename-current-conversation-title` Skill 时会安全跳过。默认 Skill 路径为 `$CODEX_HOME/skills/rename-current-conversation-title/SKILL.md`，也可通过 `CODEX_RENAME_CURRENT_TITLE_SKILL` 指定。

### Claude Code

按 Claude Code 官方方式安装并检查环境：

```bash
npm install -g @anthropic-ai/claude-code
claude --version
claude doctor
```

不要使用 `sudo npm install -g`。Windows 可使用 WSL，或配合 Git for Windows 运行 Claude Code。


用户级指令为 `~/.claude/CLAUDE.md`，项目级为 `./CLAUDE.md`；Skills 分别位于 `~/.claude/skills/` 和 `./.claude/skills/`。主指令旁同时安装 `SUBAGENTS.md`。运行 `/memory`、`/skills` 检查加载结果；首次创建顶层 Skill 目录后应重启会话。

#### 可选：DeepSeek 接入示例

以下保留原配置示例；模型可用性和参数以安装时的服务端文档为准：

| 职责 | API 标识 | 示例模型版本 |
| --- | --- | --- |
| 主代理 | `deepseek-v4-pro[1m]` | `DeepSeek-V4-Pro-0813` |
| 子代理 | `deepseek-v4-flash` | `DeepSeek-V4-Flash-0731` |

Linux、macOS、WSL 或 Git Bash 当前会话示例：

```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=<你的_DeepSeek_API_Key>
export ANTHROPIC_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
export CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash
export CLAUDE_CODE_EFFORT_LEVEL=max
export CLAUDE_CODE_AUTO_COMPACT_WINDOW=786432
```

PowerShell 当前会话示例：

```powershell
$env:ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
$env:ANTHROPIC_AUTH_TOKEN = "<你的_DeepSeek_API_Key>"
$env:ANTHROPIC_MODEL = "deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_OPUS_MODEL = "deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_SONNET_MODEL = "deepseek-v4-pro[1m]"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "deepseek-v4-flash"
$env:CLAUDE_CODE_SUBAGENT_MODEL = "deepseek-v4-flash"
$env:CLAUDE_CODE_EFFORT_LEVEL = "max"
$env:CLAUDE_CODE_AUTO_COMPACT_WINDOW = "786432"
```

如需强制自定义子代理、内置 Explore/Plan、teammates 和 workflow agents 都使用 Flash，可额外设置：

```bash
export CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1
```

```powershell
$env:CLAUDE_CODE_SUBAGENT_MODEL_FORCE = "1"
```

`CLAUDE.md` 只能声明协作规则，不能自行切换运行时模型。API Key 不得提交到 Git；需要持久化时使用操作系统的安全环境变量、密钥管理器或受保护的本地配置。

#### Hook

先预览将合并到 Claude Code 设置中的 Hook：

```bash
python Hook/install_claude.py --dry-run
```

安装到用户级 `~/.claude/settings.json`：

```bash
python Hook/install_claude.py
```

只安装到当前项目：

```bash
python Hook/install_claude.py --target .claude/settings.local.json
```

安装器会保留目标设置文件中的其他内容，替换本仓库同名处理脚本的旧条目，并在写入前创建 `.bak` 备份。重复执行不会累积重复 Hook。由于命令包含本机绝对路径，项目级安装推荐写入通常不提交的 `.claude/settings.local.json`。

安装后重启 Claude Code，运行 `/hooks` 审核配置。`SessionStart` 根据 `自动加载` 决定是否注入短摘要，`Stop` 根据 `自动收集` 决定是否登记待审核会话。

### Pi

Pi 以 npm 包分发：

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
pi --version
```

不要使用 `sudo npm install -g`。Windows 上可直接在 PowerShell 或 Git Bash 中运行；如果 `pi` 使用自带的 bash 工具，确认 `~/.pi/agent/settings.json` 的 `shellPath` 指向可用的 shell。


用户级把 `PI.AGENTS.md` 安装为 `~/.pi/agent/AGENTS.md`，项目级放在项目根 `AGENTS.md` 或 `AGENTS.override.md`，并在同目录放置 `SUBAGENTS.md`。项目级覆盖文件也会影响 Codex；多个宿主共用项目时应合并规则，不能用覆盖文件隔离 Pi 与 Codex。

Pi 模型由 `/model` 或 `settings.json` 的 `defaultProvider` / `defaultModel` 决定，本仓库不指定 Pi 模型。

Pi 原生 Skills 目录为 `~/.pi/agent/skills/` 与项目的 `.pi/skills/`，也可从 `~/.agents/skills/`、项目 `.agents/skills/` 发现技能。还可在 `settings.json` 中挂载目录：

```json
{
  "skills": ["/path/to/codex-agents-config/Skills/project-memory", "/path/to/codex-agents-config/Skills/project-memory-maintenance"]
}
```

不要同时挂载与原生目录同名的 Skill，避免只加载先发现的版本。安装后通过 `/help` 检查 `/skill:project-memory` 和 `/skill:project-memory-maintenance`。

#### Hook 扩展

Claude Code 用 `settings.json` 里的 `hooks` 执行外部命令；Pi 通过扩展订阅生命周期事件，因此这里把两个 Hook 转换成单个 Pi 扩展。

先预览将生成的扩展：

```bash
python Hook/install_pi.py --dry-run
```

安装到用户级扩展目录（默认 `$PI_CODING_AGENT_DIR/extensions/`，未设置时为 `~/.pi/agent/extensions/`）：

```bash
python Hook/install_pi.py
```

只安装到当前项目：

```bash
python Hook/install_pi.py --target .pi/extensions/project-memory-hook.ts
```

安装器会替换占位符、写入绝对路径（正斜杠，兼容 Windows），并在覆盖同名文件前创建 `.bak` 备份。由于扩展内容包含本机绝对路径，项目级安装推荐写入通常不提交的 `.pi/extensions/` 或使用用户级安装。

安装后重启 pi，或在运行中的会话执行 `/reload`。事件映射如下：

| Claude Code Hook | Pi 事件 | 行为 |
| --- | --- | --- |
| `SessionStart`（`startup\|resume\|clear\|compact\|fork`） | `session_start` + 首次 `before_agent_start` | 每个会话只注入一次已启用的当前状态或审核提示；两个开关都关闭时不注入 |
| `Stop` | `agent_settled` | 每次回复结束登记待审核会话候选，不启动模型 |

环境变量与限额：

- `PROJECT_MEMORY_VAULT`：Vault 根目录，优先于项目配置中的 `Vault根目录`。
- `PI_MEMORY_CONTEXT_CHARS`：注入摘要的字符上限，默认 4000，允许 500–12000。

扩展通过 `python <脚本> --host pi` 调用同一份 Hook 脚本，并把结果交给 Pi：摘要以不显示的 `custom_message` 注入会话，候选登记结果写入知识库的 `收件箱/`。任何失败（脚本缺失、非零退出、超过 5 秒）都会被静默忽略，不影响 Pi 会话，也不会把聊天正文写入磁盘。标题整理依赖 Codex Desktop 的 `codex-app-tools` 通道，在 Pi 中不启用。

## 初始化项目知识库

```bash
python Skills/project-memory/scripts/memory_store.py --vault-root "<Vault根目录>" --project "<项目名称>" init
```

此命令只创建基础结构。完整初始化还必须由 `project-memory` Skill 根据当前项目源码、配置和已确认约定，先通过 `upsert` 填充项目概况、主要模块导航、运行验证和核心约定等首批有来源的原子记录；模块细节和专题事实按需渐进补充，再使用 `set-current` 更新当前状态并运行 `validate`。具体步骤见 [初始化流程](Skills/project-memory/SKILL.md#初始化)。不能仅创建空结构就报告初始化完成。`validate` 对不存在的知识库及分类目录内缺失/损坏 frontmatter、缺少 ID 或必要字段的记录返回失败，不会把它们静默跳过；根目录旧式非原子笔记仍兼容。

生成结构：

```text
知识库/
├── 当前状态.md
├── 知识摘要.md（首次维护后生成）
├── 模块摘要/（按需维护生成）
├── 索引.md
├── 历史索引.md
├── 决策/
├── Bug/
├── API/
├── 架构/
├── 约定/
├── 环境/
└── 收件箱/
```

已有的 `项目架构.md`、`技术决策.md` 等旧笔记不会被覆盖或删除，可以在确认新流程稳定后逐步迁移。

## 周期维护知识库

按当前宿主调用 `project-memory-maintenance`：Codex 使用 `$project-memory-maintenance`，Claude Code 使用已发现的同名 Skill，Pi 使用 `/skill:project-memory-maintenance`。先手动运行一次：

```text
使用 project-memory-maintenance Skill 维护当前项目知识库。先按需要执行项目或单模块审计；检查摘要缺失/过期、范围不符、待复核项、同主题冗余和状态链。不要因活跃记录少于 60 条就跳过。按小批次复核并合并，不得删除历史记录；写入由单一代理串行完成，子代理只提供候选与证据。完成后报告范围、摘要 path/module、前后指标和遗留待复核项。
```

确认结果符合预期后，可让 Codex 把同一提示词配置为每周或每两周运行的自动化，并明确项目、时区与运行时间。项目记忆语义总结不挂到生命周期 Hook；标题 Hook 只处理当前对话标题。

维护脚本默认生成摘要正文最多 6,000 字符、80 行且带输入指纹和覆盖范围的项目级 `知识摘要.md`；指定单个 `--module "<模块>"` 时生成 `模块摘要/<模块名 UTF-8 的完整 SHA-256>.md`。摘要审计返回 `path` 和 `module`，模块摘要只对匹配模块、`global` 与无模块旧记录计算有效性。指纹纳入当前权威记录及明确引用历史记录的正文、模块、状态、来源和验证日期，只表示摘要输入是否变化，不能替代源码、测试或来源复核；frontmatter 的来源 ID、覆盖范围和指纹不计入正文限制。`partial` 摘要不能作为完整入口，模块 `complete` 也不代表全项目完整。大型模块可让 `当前状态.md` 保留全局约束和模块导航，把细节放入原子记录与模块摘要。`索引.md` 仍是最多 60 条、6,000 字符的活跃导航，`search` 会搜索所有分类目录；`deprecated`、`superseded` 记录进入 `历史索引.md`，`proposed` 排除权威索引与摘要但仍可被审计。摘要只有在当前任务需要作为入口时缺失或过期才触发维护，待复核和重复候选也会触发维护。

升级后旧版本摘要可能因指纹算法或覆盖状态变化一次性被标记为过期；按需重写对应摘要，旧首页若仍显示 `proposed` 可运行 `rebuild-indexes` 清理。旧原子记录仍可验证；新建或更新记录写入 `fingerprint_version: 2`，保留代码大小写和空白差异。摘要输入指纹升级后需按需重新生成，不能仅改哈希。含历史引用的旧摘要会因补入历史输入检测而过期；按需重建，纯当前事实摘要不受该变化影响。

## 自动记忆边界

- SessionStart：只有 `自动加载：是` 时才读取短 `当前状态.md`。
- 自动审核：独立开关，默认关闭；启用后 SessionStart 只提供有限候选元数据，审核由当前主代理执行，不新增模型进程。列表与审核操作见 [收件箱审核](Skills/project-memory/references/inbox-review.md)。
- Hook 输入使用 UTF-8；配置解析忽略 Markdown 围栏代码中的示例。
- Stop（记忆）：每次回复结束只登记会话 ID、仓库位置和 transcript 路径等元数据；同一宿主、同一会话使用稳定候选文件，按轮次和 transcript 版本去重。已审核的同版本不重新置为待审核，新轮次才重新标记；不启动模型。
- Stop（标题，仅 Codex Desktop）：后台先检查标题，已整理则跳过模型；需要整理时按 Skill 规则处理并读取核验。
- SessionEnd：不再作为记忆登记的必经触发点。脚本仍保留旧文件名，避免已有路径失效。
- project-memory Skill：作为普通召回入口，审核候选，并用代码、测试、提交或用户确认验证后写入正式记录。
- Codex 原生 Memories：适合个人偏好和稳定工作习惯，不作为项目权威事实来源。

这种分层可以避免把模型猜测、临时日志或未确认方案自动固化为长期记忆。

## 隐私与安全

- 仓库不包含真实 Vault 路径、用户名、密钥或内部项目资料。
- Hook 不复制完整聊天内容，只保存 transcript 的本地路径和待审核状态。
- 标题子代理只通过 Codex App-Tools 操作当前线程标题；如果 App-Tools 不可用，不通过文件或数据库修改标题。
- 正式记忆不得包含密码、令牌、私钥或其他秘密。
- 公开配置前仍应检查 Git diff 和提交内容。


普通召回入口为 `project-memory` Skill。`memory_store.py search` 默认返回 `active`、`accepted`、`fixed`，搜索所有分类目录，首轮默认 3 条、6,000 字符，可用 `--offset` 分页或扩大 `--limit`。`proposed` 不得通过合并自动提升为权威状态。审核收件箱时，`mark-inbox` 必须传审核前读取的 `--expected-updated-at`（旧候选取 `created_at`）；版本变化后需重新审核。Hook 和审核使用同一跨进程锁，避免覆盖新轮候选。

## 可选：Graphify

Graphify 用于把代码、文档和配置构建为可查询图谱。安装和初始化以 [Graphify 官方仓库](https://github.com/Graphify-Labs/graphify) 的说明为准；包名为 `graphifyy`，命令为 `graphify`。

原宿主说明中的接入方式如下，使用前核对所安装版本的支持情况：

| 宿主 | 接入方式 |
| --- | --- |
| Codex | `graphify install --platform codex`；项目级增加 `--project` |
| Claude Code | `graphify install` 注册 Skill；`graphify claude install` 写入项目指令 |
| Pi | 通过可发现的 Skill 目录加载，如 `~/.agents/skills/` |

在目标项目运行 `graphify .` 后，检查 `graphify-out/graph.html`、`GRAPH_REPORT.md` 与 `graph.json`。写入项目指令前先备份，之后检查 diff，保留现有协作与记忆规则。私有代码、文档和 API Key 的使用应遵循用户授权。

## 验证

仓库测试使用临时知识库与安装目录：

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -B -m unittest discover -s tests
```

测试覆盖记录校验、关键词覆盖排序、命中预览、分页变更、历史引用摘要失效、验证日期保留、审核提示预算、Stop 去重与审核状态、Hook 迁移、同步备份、统一安装、Vault 优先级、标题跳过与核验。实际宿主加载和模型调用需要另行验收：

| 宿主 | 检查入口 |
| --- | --- |
| Codex | 重启后检查主指令、Skills 与 `/hooks`；标题整理核对日志与实际标题 |
| Claude Code | `claude --version`、`claude doctor`、`/memory`、`/skills`、`/hooks` |
| Pi | `pi --version`、`/reload`、`/help`、`/skill:project-memory` |

对每个已安装宿主运行 `python Hook/manage_installation.py status --host <宿主>` 检查文件与 Hook 路径。用真实会话分别验证：`自动加载：是` 时注入当前状态，`否` 时不注入当前状态；`自动审核：是` 时只提示有限候选元数据并遵守总预算，默认关闭时无该提示；`自动收集：是` 时回复结束生成 `pending` 候选且不包含聊天正文。不要仅凭配置文件存在就宣称已经生效。

## 参考资料

- [Claude Code：CLAUDE.md 项目指令](https://code.claude.com/docs/en/memory)
- [Claude Code：Skills](https://code.claude.com/docs/en/skills)
- [Claude Code：Subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code：Hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code Hooks 中文参考](https://www.claude-cn.org/claude-code-docs-zh/reference/hooks.html)
- [DeepSeek：接入 Claude Code](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/claude_code/)
- [Graphify 官方仓库](https://github.com/Graphify-Labs/graphify)
- [Pi：快速开始](https://github.com/earendil-works/pi/blob/main/docs/quickstart.md)
- [Pi：Skills](https://github.com/earendil-works/pi/blob/main/docs/skills.md)
- [Pi：Extensions 与生命周期事件](https://github.com/earendil-works/pi/blob/main/docs/extensions.md)
- [Pi：设置项](https://github.com/earendil-works/pi/blob/main/docs/settings.md)
- [Pi：上下文文件与项目信任](https://github.com/earendil-works/pi/blob/main/docs/usage.md)
