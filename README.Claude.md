# Claude Code 配置

这是一套面向 Claude Code 的项目指令与项目长期记忆配置。主代理推荐使用 **DeepSeek-V4-Pro-0813**，子代理推荐使用 **DeepSeek-V4-Flash-0731**。

> 模型显示版本与 API 标识不同：主代理使用 `deepseek-v4-pro[1m]`，子代理使用 `deepseek-v4-flash`。模型版本会由服务端更新，安装时应以 DeepSeek 官方文档为准。

## 跳过文档，直接让 Agent 安装

把下面整段发给 Claude Code：

```text
请在当前环境中安装并初始化以下仓库的 Claude Code 配置：
https://github.com/fly-l/codex-agents-config.git

执行要求：
1. 将仓库克隆到合适的本地目录，先完整阅读 README.Claude.md、CLAUDE.md、两个项目记忆 Skill 及相关脚本，再根据当前操作系统执行。
2. 先询问我要安装为用户级配置（~/.claude/CLAUDE.md 与 ~/.claude/skills/）还是当前项目配置（./CLAUDE.md 与 ./.claude/skills/）。检查目标位置的现有文件，修改前备份，采用合并方式保留用户已有规则，不要直接覆盖。
3. 安装 CLAUDE.md，并复制 project-memory 与 project-memory-maintenance 两个完整 Skill 目录。Claude Code 的用户级 Skill 目录是 ~/.claude/skills/，项目级目录是 ./.claude/skills/。
4. 推荐接入 DeepSeek：主代理使用 deepseek-v4-pro[1m]，当前服务端版本为 DeepSeek-V4-Pro-0813；子代理使用 deepseek-v4-flash，当前服务端版本为 DeepSeek-V4-Flash-0731。按照 DeepSeek 官方 Claude Code 接入文档配置 ANTHROPIC_BASE_URL、ANTHROPIC_AUTH_TOKEN、ANTHROPIC_MODEL 与 CLAUDE_CODE_SUBAGENT_MODEL。API Key 只能放在安全的本地环境变量或凭据存储中，不得写入仓库、CLAUDE.md 或日志。
5. 写入项目记忆配置或初始化知识库前，先询问项目名称、Vault 根目录、是否自动加载和是否自动收集，不得猜测个人路径。Claude Code 使用 CLAUDE_MEMORY_VAULT；获得答案后更新项目 CLAUDE.md 的“知识体系”章节并初始化知识库。
6. 使用 `python Hook/install_claude.py --dry-run` 检查将生成的 Claude Hook 配置，确认后运行 `python Hook/install_claude.py`；如需项目级本地设置，使用 `--target .claude/settings.local.json`。保留现有设置内容，安装前备份，安装后运行 /hooks 审核 SessionStart 与 SessionEnd。
7. 运行 claude --version、claude doctor，并在 Claude Code 中使用 /memory 与 /skills 检查 CLAUDE.md 和两个 Skill 是否已加载。验证主代理与子代理实际使用的模型；如果运行时不支持指定模型，说明回退情况，不要假装已经切换成功。
8. 如需 Graphify，按 README.Claude.md 的“推荐插件：Graphify”章节安装，并在修改 CLAUDE.md 前创建备份、安装后检查 diff。
9. 最后报告安装位置、备份位置、模型配置、实际修改、验证结果和仍需我手动完成的步骤。未经确认，不删除现有文件或覆盖冲突配置。
```

## 配置内容

```text
.
├── CLAUDE.md
├── README.Claude.md
├── Skills/
│   ├── project-memory/
│   └── project-memory-maintenance/
└── Hook/
    ├── install.py
    ├── install_claude.py
    ├── project_memory_common.py
    ├── project_memory_session_start.py
    └── project_memory_session_end.py
```

`CLAUDE.md` 是 Claude Code 版本的主指令文件。`Skills/` 中的项目记忆逻辑由两种宿主共享；`Hook/install.py` 用于 Codex，`Hook/install_claude.py` 用于 Claude Code。

## 1. 安装 Claude Code

按 Claude Code 官方方式安装并检查环境：

```bash
npm install -g @anthropic-ai/claude-code
claude --version
claude doctor
```

不要使用 `sudo npm install -g`。Windows 可使用 WSL，或配合 Git for Windows 运行 Claude Code。

## 2. 安装 CLAUDE.md

Claude Code 支持两种常用作用域：

- 用户级：`~/.claude/CLAUDE.md`，适用于本机所有项目。
- 项目级：`./CLAUDE.md`，适用于当前仓库，可提交给团队共享。

目标文件已存在时应先备份并合并，不能直接覆盖。启动 Claude Code 后运行 `/memory`，确认目标 `CLAUDE.md` 已被加载。

## 3. 配置 DeepSeek 主代理与子代理

推荐模型映射：

| 职责 | API 标识 | 当前模型版本 |
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

## 4. 安装项目记忆 Skills

用户级安装路径：

```text
~/.claude/skills/project-memory/
~/.claude/skills/project-memory-maintenance/
```

项目级安装路径：

```text
.claude/skills/project-memory/
.claude/skills/project-memory-maintenance/
```

必须复制完整目录，包括 `SKILL.md`、`references/`、`scripts/` 和其他随附文件。安装后运行 `/skills` 检查发现结果；如果运行中的会话首次创建了顶层 Skill 目录，应重启 Claude Code。

当前 Skill 由 Codex 与 Claude Code 共享，并已按宿主区分项目指令文件和环境变量。Claude Code 从项目级 `CLAUDE.md` 读取“知识体系”，Claude Hook 处理脚本在 `--host claude` 模式下优先使用：

```bash
export CLAUDE_MEMORY_VAULT="<Vault根目录>"
```

也可以在项目级 `CLAUDE.md` 的“知识体系”章节写入私有 `Vault根目录`，但不要把个人路径提交到公开仓库。

## 5. 配置与初始化项目知识库

在项目级 `CLAUDE.md` 中增加：

```markdown
## 知识体系
- 启用：是
- 项目名称：示例项目
- 自动加载：否
- 自动收集：是
```

`自动加载：否` 是推荐值，避免每次启动都注入项目状态；`自动收集：是` 只会在 SessionEnd 登记待审核会话元数据，不会自动提升为权威记忆。初始化命令：

```bash
python "<project-memory Skill目录>/scripts/memory_store.py" \
  --vault-root "<Vault根目录>" \
  --project "<项目名称>" \
  init
```

此命令只创建缺失目录和基础索引，不会覆盖已有笔记。完整初始化还必须由 `project-memory` Skill 根据当前项目源码、配置和已确认约定，先通过 `upsert` 填充项目概况、主要模块导航、运行验证和核心约定等首批有来源的原子记录；模块细节和专题事实按需渐进补充，再使用 `set-current` 更新当前状态并运行 `validate`。具体步骤见 [初始化流程](Skills/project-memory/SKILL.md#初始化)。不能仅创建空结构就报告初始化完成。

规模较大的项目可以在知识库中按需创建 `模块摘要/`，模块摘要文件名使用模块名 UTF-8 编码后的完整 SHA-256。`当前状态.md` 保留全局约束和模块导航，不要求项目级摘要容纳所有模块细节。

## 6. 安装 Claude Code Hooks

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

安装后重启 Claude Code，运行 `/hooks` 审核配置。`SessionStart` 根据 `自动加载` 决定是否注入短摘要，`SessionEnd` 根据 `自动收集` 决定是否登记待审核会话。

## 7. 周期维护项目知识库

先手动运行一次：

```text
使用 $project-memory-maintenance 维护当前项目知识库。先按需要执行项目或单模块审计；检查摘要缺失/过期、范围不符、待复核项、同主题冗余和状态链。不要因活跃记录少于 60 条就跳过。按小批次复核并合并，不得删除历史记录；写入由单一代理串行完成，子代理只提供候选与证据。完成后报告范围、摘要 path/module、前后指标和遗留待复核项。
```

维护脚本默认写入摘要正文最多 6,000 字符、80 行的项目级 `知识摘要.md`；指定单个 `--module "<模块>"` 时写入 `模块摘要/<模块名 UTF-8 的完整 SHA-256>.md`。审计会读取正文计算输入指纹，但不会把全量正文注入模型；指纹纳入正文、模块、状态、来源和验证日期等知识输入，只表示摘要输入是否变化，不能替代源码、测试或来源复核；frontmatter 的来源 ID、覆盖范围和指纹不计入正文限制。模块摘要只对匹配模块、`global` 与无模块旧记录计算有效性；无模块记录必须复核范围。`partial` 摘要不能作为完整入口，模块 `complete` 也不代表全项目完整。`proposed` 排除权威索引与摘要但仍可被审计，不得通过合并自动提升为 `accepted`、`active`，经用户确认并复核后按记录流程处理。

普通召回入口以 `project-memory` Skill 为准；需要定向搜索时，`memory_store.py search` 默认只返回 `active`、`accepted`、`fixed`，查询所有分类目录，不受首页 60 条限制，首轮默认 3 条、6,000 字符，可用 `--offset` 分页或扩大 `--limit`。摘要缺失或过期在当前任务需要它作为入口时才触发维护；待复核项和重复候选也会触发维护。

升级后旧版本摘要可能因指纹算法或覆盖状态变化一次性被标记为过期；按需重写对应摘要，旧首页若仍显示 `proposed` 可运行 `rebuild-indexes` 清理。该兼容处理不修改原子记录格式，也不要求迁移旧原子记录。

## 8. 推荐插件：Graphify

Graphify 可以把代码、文档和配置构建为可查询的知识图谱。可把下面整段发给 Claude Code：

```text
请为当前 Claude Code 环境安装并初始化 Graphify，官方仓库：
git@github.com:Graphify-Labs/graphify.git

先阅读官方最新 README。确认 Python 3.10+ 后，优先使用 `uv tool install graphifyy`，没有 uv 时使用 pipx；注意 PyPI 包名是 graphifyy，CLI 命令是 graphify。随后使用 `graphify install` 注册 Claude Code Skill，在当前项目根目录运行 `graphify .` 创建知识图谱，再运行 `graphify claude install` 将查询优先规则写入项目 CLAUDE.md。修改 CLAUDE.md 前必须备份，完成后检查 diff，并验证 graphify-out/graph.html、GRAPH_REPORT.md 和 graph.json 已生成。不要配置或上传未经我确认的 API Key、私有代码或文档。
```

`graphify claude install` 会修改项目的 `CLAUDE.md`。如果本仓库配置已安装，必须先备份并检查合并结果，避免覆盖模型分工、项目记忆和多代理规则。

## 9. 验证清单

- `claude --version` 与 `claude doctor` 正常。
- `/memory` 能看到预期作用域的 `CLAUDE.md`。
- `/skills` 能看到 `project-memory` 与 `project-memory-maintenance`。
- 主代理实际使用 `deepseek-v4-pro[1m]`，子代理实际使用 `deepseek-v4-flash`；不能只根据文件中的文字判断。
- API Key、Vault 真实路径和个人信息未进入 Git diff。
- Claude Hook 已写入预期的用户级或项目级 `settings.json`，`/hooks` 能看到 SessionStart 与 SessionEnd。

## 隐私与安全

- 不在仓库中保存 API Key、令牌、密码、个人 Vault 路径或内部项目资料。
- 安装前备份现有 `CLAUDE.md`、`.claude/settings*.json` 和 Skill 目录。
- 第三方模型服务会接收发送给模型的上下文；使用私有代码与文档前应确认组织政策及数据处理要求。
- 正式项目记忆必须有可核验来源，未经验证的会话内容不能直接提升为权威事实。

## 参考资料

- [Claude Code：CLAUDE.md 项目指令](https://code.claude.com/docs/en/memory)
- [Claude Code：Skills](https://code.claude.com/docs/en/skills)
- [Claude Code：Subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code：Hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code Hooks 中文参考](https://www.claude-cn.org/claude-code-docs-zh/reference/hooks.html)
- [DeepSeek：接入 Claude Code](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/claude_code/)
- [Graphify 官方仓库](https://github.com/Graphify-Labs/graphify)
