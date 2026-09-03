# 跳过这个 README 吧

读文档的时代已经过去了。直接把下面这段发给你的 Agent：

```text
请在当前环境中安装并初始化以下 Codex 配置仓库：
https://github.com/fly-l/codex-agents-config.git

执行要求：
1. 将仓库克隆到合适的本地目录，先完整阅读仓库中的 README.md、AGENTS.md 和 Hook/install.py，再根据当前操作系统执行安装。
2. 检查 CODEX_HOME（未设置时使用 ~/.codex）以及已有的 AGENTS.md、config.toml 和 hooks.json。修改前创建备份，保留并合并已有配置，不要直接覆盖用户内容。
3. 按仓库说明安装根目录的 AGENTS.md、project-memory 与 project-memory-maintenance Skills，以及 SessionStart、SessionEnd Hooks；如未启用 Hooks，安全地将 hooks = true 合并到 config.toml 的 [features] 配置中。
4. 写入项目记忆配置或初始化知识库前，先询问我的项目名称、Vault 根目录、是否自动加载和是否自动收集；不得猜测个人路径。获得答案后，更新当前项目 AGENTS.md 的“知识体系”章节并初始化知识库。
5. 运行安装脚本提供的 dry-run 或其他适用检查，验证 Skills 已安装、hooks.json 格式有效、Hook 路径可用，并说明是否需要重启 Codex 及运行 /hooks 进行确认。
6. 最后报告安装位置、备份位置、实际修改、验证结果以及仍需我手动完成的步骤。未经确认，不删除现有文件，也不覆盖有冲突的配置。
```

## 推荐插件

推荐安装 Graphify。把下面这段发给 Agent，即可完成安装和项目初始化：

```text
请在当前环境中安装 Graphify，并为当前 Codex 项目完成初始化。官方仓库：
git@github.com:Graphify-Labs/graphify.git

执行要求：
1. 先阅读官方仓库的最新 README 和安装说明，检查当前操作系统、Python 版本及已有安装，避免破坏现有 Python 和 Codex 配置。
2. 确认 Python 版本不低于 3.10，优先使用隔离环境执行 `uv tool install graphifyy`；没有 uv 时使用官方支持的 pipx 方案。注意官方 PyPI 包名是 `graphifyy`（双 y），CLI 命令才是 `graphify`，不要安装其他同名包。
3. 使用 `graphify install --platform codex` 注册 Codex Skill；若适合仅在当前仓库启用，则使用 `graphify install --project --platform codex`。修改已有配置前先备份并采用合并方式。
4. 检查 Codex 的 `~/.codex/config.toml`，将 `multi_agent = true` 安全地合并到 `[features]`，保留其他配置；如变更需要重启 Codex，明确提示我。
5. 在当前项目根目录初始化知识图谱。PowerShell 中使用 `graphify .`；在 Codex 对话中使用 `$graphify`。不要未经确认配置或上传任何 API 密钥、私有代码或文档。
6. 验证 `graphify` 命令和 Skill 可用，并确认生成了 `graphify-out/graph.html`、`graphify-out/GRAPH_REPORT.md` 与 `graphify-out/graph.json`。最后报告安装版本、配置变更、生成文件和任何失败项。
```

# Codex AGENTS 配置

这是一套可复用的 Codex 配置，包含精简的运行时 `AGENTS.md`、按需加载的项目记忆 Skill、周期维护 Skill，以及基于生命周期事件的 Hook。

## 设计目标

- 全局 `AGENTS.md` 只保留必须始终生效的路由与约束。
- 项目记忆默认延迟召回，不在每次会话开始时读取整个知识库。
- 活跃索引与历史索引分离；活跃入口最多 60 条、6,000 字符，已替代记录不会持续占用普通召回上下文。
- 周期维护先做元数据审计，再按小批次总结同主题记录，不全量加载知识库正文。
- 正式记录使用稳定 ID、状态、来源、验证日期和内容指纹。
- 写入采用原子化 upsert，不使用盲目 `append`，不手工制造反向链接。
- Hook 只登记待审核会话；聊天内容不会未经验证直接成为权威记忆。
- 保留原有多代理委派、冲突控制与验收规则。

## 目录

```text
.
├── AGENTS.md
├── Skills/
│   ├── project-memory/
│       ├── SKILL.md
│       ├── references/schema.md
│       └── scripts/memory_store.py
│   └── project-memory-maintenance/
│       ├── SKILL.md
│       ├── references/consolidation.md
│       └── scripts/memory_maintenance.py
└── Hook/
    ├── hooks.json
    ├── install.py
    ├── project_memory_common.py
    ├── project_memory_session_start.py
    └── project_memory_session_end.py
```

## 1. 安装 AGENTS 配置

将根目录的 `AGENTS.md` 放入 Codex 全局配置目录。Codex 默认使用 `~/.codex/AGENTS.md`；也可以将需要的部分放入具体项目。

项目级 `AGENTS.md` 增加：

```markdown
## 知识体系
- 启用：是
- 项目名称：示例项目
- 自动加载：否
- 自动收集：是
```

`自动加载：否` 是推荐值：只有任务需要历史信息时才调用 Skill。改成 `是` 后，SessionStart Hook 会注入最多约 4,000 字符的 `当前状态.md`。

## 2. 配置 Vault 路径

推荐使用环境变量，不要把个人路径提交到公开仓库：

```powershell
$env:CODEX_MEMORY_VAULT = "D:\ObsidianNoteHub\项目代码"
```

也可以在私有的项目级 `AGENTS.md` 的 `知识体系` 章节设置：

```markdown
- Vault根目录：D:\ObsidianNoteHub\项目代码
```

环境变量的优先级更高。

## 3. 安装项目记忆 Skills

将两个项目记忆 Skill 复制到 Codex Skills 目录。Windows PowerShell 示例：

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { "$HOME\.codex" }
New-Item -ItemType Directory -Force "$codexHome\skills" | Out-Null
Copy-Item -Recurse -Force ".\Skills\project-memory" "$codexHome\skills\project-memory"
Copy-Item -Recurse -Force ".\Skills\project-memory-maintenance" "$codexHome\skills\project-memory-maintenance"
```

安装后可通过 `$project-memory` 检索或记录长期事实，通过 `$project-memory-maintenance` 审计、总结和去重知识库。

## 4. 安装 Hook

Hook 源文件全部位于 `Hook/`。安装脚本会把 SessionStart 和 SessionEnd 配置合并到现有 `hooks.json`，并在覆盖前创建 `.bak` 备份：

```bash
python Hook/install.py
```

只查看将生成的配置：

```bash
python Hook/install.py --dry-run
```

如果当前 Codex 配置尚未启用 Hook，在 `~/.codex/config.toml` 中加入：

```toml
[features]
hooks = true
```

重启 Codex 后运行 `/hooks`，审核并信任新增 Hook。仓库中的 `Hook/hooks.json` 是使用 `CODEX_AGENTS_CONFIG_ROOT` 环境变量的便携模板；通常直接运行安装脚本更简单，因为它会生成绝对路径。

## 5. 初始化项目知识库

```bash
python Skills/project-memory/scripts/memory_store.py \
  --vault-root "<Vault根目录>" \
  --project "<项目名称>" \
  init
```

生成结构：

```text
知识库/
├── 当前状态.md
├── 知识摘要.md（首次维护后生成）
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

## 6. 周期维护知识库

先手动运行一次：

```text
使用 $project-memory-maintenance 维护当前项目知识库。先审计；仅在活跃索引超过建议范围、存在同主题冗余或状态链未收敛时分批复核并合并。不得删除历史记录。完成后报告前后指标。
```

确认结果符合预期后，可让 Codex 把同一提示词配置为每周或每两周运行的自动化，并明确项目、时区与运行时间。不要把语义总结挂到 SessionStart 或 SessionEnd；这两个 Hook 继续只负责短摘要注入和候选登记。

维护脚本生成最多 6,000 字符、80 行且带输入指纹和覆盖范围的 `知识摘要.md`，把 `索引.md` 控制为最多 60 条、6,000 字符的活跃入口，并将 `deprecated`、`superseded` 记录放进 `历史索引.md`。摘要过期或覆盖不完整时 `$project-memory` 会回退到同样有硬上限的活跃索引；历史原文仍保留在原子笔记中，需要追溯时才加载。

## 自动记忆边界

- SessionStart：只有 `自动加载：是` 时才读取短 `当前状态.md`。
- SessionEnd：只向 `收件箱/` 写入会话 ID、仓库位置和 transcript 路径等元数据。
- project-memory Skill：审核候选，并用代码、测试、提交或用户确认验证后写入正式记录。
- Codex 原生 Memories：适合个人偏好和稳定工作习惯，不作为项目权威事实来源。

这种分层可以避免把模型猜测、临时日志或未确认方案自动固化为长期记忆。

## 隐私与安全

- 仓库不包含真实 Vault 路径、用户名、密钥或内部项目资料。
- Hook 不复制完整聊天内容，只保存 transcript 的本地路径和待审核状态。
- 正式记忆不得包含密码、令牌、私钥或其他秘密。
- 公开配置前仍应检查 Git diff 和提交内容。
