---
name: project-memory-maintenance
description: 定期审计、总结和去重项目长期记忆，缩小 project-memory 的活跃索引与召回上下文。用于用户要求整理知识库、压缩记忆、清理冗余或为项目记忆设置周期维护时；不用于普通的历史检索和单条记录写入。
---

# 项目记忆维护

通过短活跃索引、可追溯历史记录和按模块摘要降低召回成本。维护不删除正式记录；旧事实保留原文，标为 `superseded` 或 `deprecated` 后移出活跃入口。

## 启用检查

复用 `project-memory` 配置：`启用` 必须为 `是`，`项目名称` 必须存在；Codex 与 Pi 从 `AGENTS.md` 读取，Claude Code 从 `CLAUDE.md` 读取。Vault 统一优先 `PROJECT_MEMORY_VAULT`，其次为 `Vault根目录`。缺失时停止，不猜路径。

## 选择与流程

- 普通具体问题仍走 `$project-memory` 的定向 `search`；仅了解模块概况时用 `maintenance-audit --summary-only --module`。本 Skill 的 `audit` 是维护用的完整审计，不应成为普通回忆入口。
- 维护前运行 `memory_maintenance.py audit`，项目级或追加单个 `--module`。检查摘要缺失、过期或范围不符、待复核收件箱、重复或冲突、索引接近限制及状态链；记录少于 60 条不能单独作为跳过理由。
- 需要定向查找时按 [召回与复核](../project-memory/references/retrieval.md) 使用 `search`；默认取 3 条、按需分页，并复核模块、`global` 和无模块旧记录的适用范围。
- 按 [合并规则](references/consolidation.md) 小批次复核候选。用当前代码、测试、提交或用户确认确认事实；`proposed` 不得自动提升为权威状态，冲突不得猜选。
- 写入由指定的唯一代理串行完成：纯措辞沿用原 ID，实质变化新建 ID 并设置 `supersedes`；更新时传入 `--expected-fingerprint`。不删除原子记录，已处理收件箱只能可恢复归档。
- 只有摘要确实需要重建时运行 `write-summary`；正文不超过 6,000 字符和 80 行，`coverage: complete` 只表示当前审计范围完整。最后运行 `validate`，按同一范围再次审计并报告前后指标、摘要 `path`/`module`、跳过冲突和待复核项。

## 约束

摘要输入指纹只说明知识输入变化，不能替代源码、测试或来源验证。模块审计和摘要只覆盖匹配模块、`global` 与无模块旧记录；模块完整不等于全项目完整。没有变化时快速结束，不为填充摘要制造记录。
