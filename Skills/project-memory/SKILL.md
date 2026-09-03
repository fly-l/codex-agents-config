---
name: project-memory
description: 检索、初始化和维护项目级长期记忆。仅在任务依赖历史决策、架构、Bug、API 模式、约定或环境事实，或产生了需要长期保留的已验证信息时使用。
---

# 项目长期记忆

将 Obsidian 知识库视为可审计的项目事实库，而不是聊天记录仓库。普通任务若不依赖历史信息且未产生持久事实，不要加载或写入记忆。

## 启用检查

从当前宿主已加载的项目级指令文件的 `知识体系` 章节读取：Codex 使用 `AGENTS.md`，Claude Code 使用 `CLAUDE.md`。

- `启用` 必须为 `是`。
- `项目名称` 必须存在。
- Vault 根目录优先使用当前宿主的环境变量：Codex 使用 `CODEX_MEMORY_VAULT`，Claude Code 使用 `CLAUDE_MEMORY_VAULT`；其次使用 `Vault根目录` 配置。

缺少任一必要值时停止记忆操作。不要猜测路径，不要创建替代目录。

## 选择工作模式

- **回忆**：任务明确涉及既有决策、模块关系、历史 Bug、API 使用方式、代码约定或环境配置。
- **记录**：当前工作产生了用户已确认或由代码、测试、提交证明的重要信息。
- **初始化**：知识体系已启用，但项目知识库尚不存在。
- **审核收件箱**：Hook 留下待处理会话，且当前任务需要恢复相关历史或用户明确要求整理记忆。

## 回忆

1. 如果 `知识库/知识摘要.md` 存在，先用 `memory_store.py maintenance-audit` 检查 `summary.usable`。仅当输入指纹未过期且 `coverage: complete` 时先读这个有硬上限的摘要；否则读有 6,000 字符硬上限的活跃 `知识库/索引.md`。默认最多返回 3 条相关摘要。
2. 忽略 `status: superseded|deprecated` 的记录，除非任务询问历史原因。
3. 只有任务追溯旧决定或变更原因时才读取 `知识库/历史索引.md`。需要细节时才读取完整原子笔记；不要扫描整个 Vault。
4. 用当前代码、测试或用户确认校验可能过期的事实。
5. 回答时区分“当前事实”“历史决定”和“尚待验证”。

如果项目设置 `自动加载：是`，Hook 可能已注入 `当前状态.md`。它只是导航摘要，不能替代源码或正式记录。

## 记录

写入前阅读 [记录结构](references/schema.md)，然后：

1. 为信息选择类型、稳定 ID、状态、来源和验证日期。
2. 搜索相同 ID 和相同主题；相同 ID 应更新，不能新建重复记录。
3. 使用 `scripts/memory_store.py upsert` 原子写入。不要用 `obsidian append` 拼接章节。
4. 新记录替代旧记录时设置 `supersedes`；存储脚本会把旧记录状态改为 `superseded`，并从活跃索引移入历史索引。
5. 运行 `scripts/memory_store.py validate`，确认没有重复 ID 或指纹。

正式记录必须有可核验来源。用户明确确认可以作为来源；代码事实应尽量包含文件位置、提交 SHA 或测试命令。

## 初始化

命令中的脚本路径应从本 `SKILL.md` 所在目录解析，不要假设当前项目包含 `Skills/` 源码目录。

运行：

```bash
python "<project-memory Skill目录>/scripts/memory_store.py" \
  --vault-root "<Vault根目录>" \
  --project "<项目名称>" \
  init
```

初始化只创建缺失目录和基础索引，不覆盖现有笔记。

## 审核 Hook 收件箱

`知识库/收件箱/*.json` 只记录待审核会话元数据：

1. 仅处理与当前任务有关的候选。
2. 如果 `transcript_path` 仍存在，提取可能重要的信息并以源码、测试或用户确认复核。
3. 通过 `upsert` 写入正式记录后，使用 `mark-inbox` 标记为 `processed`。
4. 没有长期价值的候选标记为 `ignored`。

不得直接把完整聊天或 Hook 候选复制进正式知识库。

## 当前状态

仅当项目当前架构、关键约束或进行中事项确实发生变化时更新 `当前状态.md`：

```bash
python "<project-memory Skill目录>/scripts/memory_store.py" \
  --vault-root "<Vault根目录>" \
  --project "<项目名称>" \
  set-current \
  --body-file "<摘要文件>"
```

保持摘要不超过 80 行；详细历史留在原子笔记中。

当活跃索引或同主题记录持续增长时，使用 `$project-memory-maintenance` 做分批审计和语义合并；普通回忆不要顺带扫描、总结整个知识库。
