# 项目记忆结构

## 目录

```text
{Vault根目录}/{项目名称}/知识库/
├── 当前状态.md
├── 索引.md
├── 决策/
├── Bug/
├── API/
├── 架构/
├── 约定/
├── 环境/
└── 收件箱/
```

`当前状态.md` 只保存仍然有效的短摘要，建议不超过 80 行。历史事实分别保存为原子笔记；每日记录或 Hook 产生的候选记录不能作为权威事实直接召回。

`知识摘要.md` 由 `project-memory-curator` 按需生成，只汇总当前有效知识并引用原子记录 ID。它用于导航和降低重复读取成本，不替代源码、测试或原子记录。

## 记录字段

每条正式记录至少包含：

| 字段 | 含义 |
|---|---|
| `id` | 稳定且唯一的标识，如 `ADR-20260829-001` |
| `type` | `decision`、`bug`、`api`、`architecture`、`convention` 或 `environment` |
| `status` | `proposed`、`accepted`、`active`、`fixed`、`deprecated` 或 `superseded` |
| `source` | 用户确认、代码位置、提交 SHA、测试或文档 URL |
| `verified_at` | 最近验证日期 |
| `fingerprint` | 规范化内容的 SHA-256 指纹，用于去重 |
| `supersedes` | 被当前记录替代的旧记录 ID |
| `superseded_by` | 旧记录被替代时指向当前保留记录 ID |

推荐 ID：

- 架构或技术决策：`ADR-YYYYMMDD-NNN`
- Bug：`BUG-YYYYMMDD-NNN`
- API 模式：`API-库名-主题`
- 架构事实：`ARCH-模块名-主题`
- 约定：`CONV-主题`
- 环境：`ENV-主题`

ID 一旦创建不得因标题修改而变化。

## 来源优先级

发生冲突时按以下顺序判断：

1. 当前代码、测试结果和已合并提交
2. 用户在当前会话中明确确认的决定
3. `status: active|accepted|fixed` 且最近验证的记录
4. 历史记录和 Hook 收件箱候选

低优先级内容不得覆盖高优先级事实。发现冲突时保留旧记录，将其标记为 `superseded` 或 `deprecated`；新记录用 `supersedes` 指向旧记录，旧记录用 `superseded_by` 指回新记录。

## 写入边界

可以写入：已经确认的决策、可复现且已修复的 Bug、经过验证的 API 用法、稳定代码约定、当前环境事实。

不得写入：秘密、访问令牌、个人敏感路径、未确认方案、一次性日志、模型猜测、没有来源的结论。
