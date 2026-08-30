---
name: project-memory-curator
description: 审计、总结、去重和压缩 project-memory 项目知识库。用户要求整理知识库、生成知识摘要、合并近义记忆、处理陈旧记录或归档已审核收件箱时使用；普通历史检索与单条写入使用 project-memory。
---

# 项目记忆整理

在保留来源和历史记录的前提下减少知识库冗余，并生成短、可追溯的 `知识摘要.md`。脚本只发现候选，不把相似度当作事实，也不删除原子记录。

## 前置检查

从已加载的项目级 `AGENTS.md` 的 `知识体系` 章节取得 `启用`、`项目名称` 和 Vault 路径。仅当 `启用：是` 且路径完整时继续；不得猜测路径。

## 1. 审计

先运行：

```bash
python Skills/project-memory-curator/scripts/memory_curator.py \
  --vault-root "<Vault根目录>" --project "<项目名称>" audit
```

审计只读取正式原子记录和收件箱元数据，输出：完全重复、近义候选、同标题冲突、超过 180 天未验证的记录、缺失字段以及摘要状态。不要扫描整个 Vault 或完整会话 transcript。

## 2. 整理候选

按以下顺序处理，并一次只读一个候选组的完整笔记：

1. 完全重复。
2. 同标题但内容不同的潜在冲突。
3. 高相似度近义记录。
4. 陈旧或来源缺失的记录。

用当前代码、测试、提交或用户确认复核。选择来源更强、验证更新且 ID 更稳定的记录作为保留记录；先把其他记录中仍有效的独有信息合并到保留记录，再标记替代关系。不得仅凭相似度合并，不得覆盖未解决的冲突。

使用 `project-memory` 的 `upsert` 更新保留记录并列出 `supersedes`。随后先预览，再在用户已经要求执行整理写入时应用：

```bash
python Skills/project-memory-curator/scripts/memory_curator.py \
  --vault-root "<Vault根目录>" --project "<项目名称>" supersede \
  --canonical "<保留ID>" --duplicate "<重复ID>" --reason "<核验依据>"

# 确认预览后追加 --apply
```

该操作不删除旧笔记，只将其标记为 `superseded` 并写入 `superseded_by`。

## 3. 生成知识摘要

摘要只保留当前有效的架构、决策、约定、已知风险和环境要点。每个要点写出来源 ID；细节留在原子记录，不复制长段正文。

准备不超过 120 行的 Markdown 正文后运行：

```bash
python Skills/project-memory-curator/scripts/memory_curator.py \
  --vault-root "<Vault根目录>" --project "<项目名称>" write-summary \
  --body-file "<摘要正文>" --source-id "<记录ID>"
```

每个 `--source-id` 必须出现在摘要正文中。默认不得引用 `deprecated` 或 `superseded` 记录。

## 4. 收尾

- 再次运行 `audit`，确认候选数量按预期下降且没有缺失字段。
- 运行 `project-memory/scripts/memory_store.py validate`。
- 已处理或忽略超过 30 天的收件箱条目可用 `archive-inbox` 预览，用户已要求归档时再加 `--apply`；归档只移动文件，不删除。
- 汇报保留、合并、停用和待确认的记录；无法核验的冲突保持原状。
