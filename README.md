# Codex AGENTS 配置

这是一套可复用的 Codex 配置，包含精简的运行时 `AGENTS.md`、按需加载的项目记忆 Skill、知识库整理 Skill，以及基于生命周期事件的 Hook。

## 设计目标

- 全局 `AGENTS.md` 只保留必须始终生效的路由与约束。
- 项目记忆默认延迟召回，不在每次会话开始时读取整个知识库。
- 正式记录使用稳定 ID、状态、来源、验证日期和内容指纹。
- 写入采用原子化 upsert，不使用盲目 `append`，不手工制造反向链接。
- Hook 只登记待审核会话；聊天内容不会未经验证直接成为权威记忆。
- 知识库整理采用“脚本发现候选、模型核验语义、无损标记替代”的方式，不自动删除原始记录。
- 多代理规则只保留委派条件、写入边界与验收要求，避免通用说明长期占用上下文。

## 目录

```text
.
├── AGENTS.md
├── Skills/
│   ├── project-memory/
│   │   ├── SKILL.md
│   │   ├── references/schema.md
│   │   └── scripts/memory_store.py
│   └── project-memory-curator/
│       ├── SKILL.md
│       └── scripts/memory_curator.py
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

`自动加载：否` 是推荐值：只有任务需要历史信息时才调用 Skill。改成 `是` 后，SessionStart Hook 默认注入最多约 2,400 字符的 `当前状态.md`；可用 `CODEX_MEMORY_CONTEXT_CHARS` 在 500–6,000 字符内调整。

## 2. 配置 Vault 路径

推荐使用环境变量，不要把个人路径提交到公开仓库：

```powershell
$env:CODEX_MEMORY_VAULT = "<Vault根目录>"
```

也可以在私有的项目级 `AGENTS.md` 的 `知识体系` 章节设置：

```markdown
- Vault根目录：<Vault根目录>
```

环境变量的优先级更高。

## 3. 安装记忆 Skills

将两个 Skill 复制到 Codex Skills 目录。Windows PowerShell 示例：

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { "$HOME\.codex" }
New-Item -ItemType Directory -Force "$codexHome\skills" | Out-Null
Copy-Item -Recurse -Force ".\Skills\project-memory" "$codexHome\skills\project-memory"
Copy-Item -Recurse -Force ".\Skills\project-memory-curator" "$codexHome\skills\project-memory-curator"
```

安装后：

- `$project-memory`：检索、验证和写入原子记忆。
- `$project-memory-curator`：审计近义/冲突/陈旧记录，生成知识摘要并无损去重。

两个 Skill 都支持按描述自动匹配；普通任务只会看到简短元数据，不会加载完整说明或脚本。

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
├── 知识摘要.md（首次整理后生成）
├── 索引.md
├── 决策/
├── Bug/
├── API/
├── 架构/
├── 约定/
├── 环境/
└── 收件箱/
```

已有的 `项目架构.md`、`技术决策.md` 等旧笔记不会被覆盖或删除，可以在确认新流程稳定后逐步迁移。

## 6. 整理并总结知识库

先运行只读审计：

```bash
python Skills/project-memory-curator/scripts/memory_curator.py \
  --vault-root "<Vault根目录>" \
  --project "<项目名称>" \
  audit
```

审计报告会列出：完全重复、近义候选、同标题冲突、超过 180 天未验证的记录、元数据缺失、收件箱数量和摘要状态。相似记录不会自动合并；`project-memory-curator` 会逐组读取并核验来源，保留更可靠的记录，把其他记录无损标记为 `superseded`，然后生成带来源 ID 的 `知识摘要.md`。

已处理或忽略超过 30 天的收件箱条目可先预览归档：

```bash
python Skills/project-memory-curator/scripts/memory_curator.py \
  --vault-root "<Vault根目录>" \
  --project "<项目名称>" \
  archive-inbox
```

确认后追加 `--apply`。归档只移动到 `收件箱/归档/<年份>/`，不删除文件。

## 自动记忆边界

- SessionStart：只有 `自动加载：是` 时才读取短 `当前状态.md`。
- SessionEnd：只向 `收件箱/` 写入会话 ID、仓库位置和 transcript 路径等元数据。
- project-memory Skill：审核候选，并用代码、测试、提交或用户确认验证后写入正式记录。
- project-memory-curator Skill：按需审计和压缩正式记录；所有语义合并保留旧记录及替代关系。
- Codex 原生 Memories：适合个人偏好和稳定工作习惯，不作为项目权威事实来源。

这种分层可以避免把模型猜测、临时日志或未确认方案自动固化为长期记忆。

## 隐私与安全

- 仓库不包含真实 Vault 路径、用户名、密钥或内部项目资料。
- Hook 不复制完整聊天内容，只保存 transcript 的本地路径和待审核状态。
- 正式记忆不得包含密码、令牌、私钥或其他秘密。
- 公开配置前仍应检查 Git diff 和提交内容。
