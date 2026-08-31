# 项目记忆结构

## 目录

```text
{Vault根目录}/{项目名称}/知识库/
├── 当前状态.md
├── 知识摘要.md
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

`当前状态.md` 只保存当前架构、关键约束和进行中事项，最多 80 行、6,000 字符。`知识摘要.md` 是周期维护生成的稳定知识导航，最多 80 行、6,000 字符，并用 `source_fingerprint` 标记输入版本、用 `coverage` 区分完整或局部覆盖；过期或局部摘要不得作为默认召回入口。`索引.md` 只列出活跃记录，最多 60 条、6,000 字符；`历史索引.md` 列出 `deprecated` 和 `superseded` 记录，仅在追溯历史时读取。历史事实分别保存为原子笔记；每日记录或 Hook 产生的候选记录不能作为权威事实直接召回。

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

低优先级内容不得覆盖高优先级事实。发现冲突时保留旧记录，将其标记为 `superseded` 或 `deprecated`，并通过 `supersedes` 建立关系。

设置 `supersedes` 后，存储脚本会保留旧文件、写入 `superseded_by`，并把旧记录移出活跃索引；不得为了压缩上下文删除历史原文。

## 写入边界

可以写入：已经确认的决策、可复现且已修复的 Bug、经过验证的 API 用法、稳定代码约定、当前环境事实。

不得写入：秘密、访问令牌、个人敏感路径、未确认方案、一次性日志、模型猜测、没有来源的结论。
