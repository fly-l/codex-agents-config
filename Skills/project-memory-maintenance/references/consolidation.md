# 语义合并规则

## 候选选择

先运行深度候选审计；它不会自动合并：

```bash
python "<本 Skill目录>/scripts/memory_maintenance.py" \
  --vault-root "<Vault根目录>" \
  --project "<项目名称>" \
  audit
```

优先处理以下候选：

1. 相同 `type`、相同 `module`，且描述同一接口、约定、架构边界或 Bug 根因的记录。
2. 新记录明确替代旧记录，但旧记录仍处于活跃状态。
3. 多条记录只有时间、措辞或局部示例不同，核心约束相同。
4. 长期未验证且与当前代码可能冲突的活跃记录；这类记录应先复核，不能直接合并。

不要仅因标题相似就合并。独立决策、不同适用范围、需要分别追溯的事故与尚未解决的冲突应保持独立。

## 摘要记录

摘要记录沿用原有 `type`，不要新增通用 `summary` 类型。优先更新已有的稳定主题 ID；没有合适 ID 时，为该主题创建一个可长期复用的 ID。

正文只保留：

- 当前有效结论；
- 适用模块和边界；
- 会改变实现选择的例外；
- 必要的验证方式；
- 被合并记录的 ID 或其他可核验来源。

不要复制完整历史、长日志、聊天内容和重复示例。历史原因留在被替代的原子记录中。

示例命令：

```bash
python "<project-memory Skill目录>/scripts/memory_store.py" \
  --vault-root "<Vault根目录>" \
  --project "<项目名称>" \
  upsert \
  --kind architecture \
  --id "ARCH-memory-retrieval" \
  --title "项目记忆召回边界" \
  --body-file "<已复核摘要文件>" \
  --status active \
  --source "代码、测试或用户确认" \
  --module "project-memory" \
  --supersedes "ARCH-memory-index-v1" \
  --supersedes "ARCH-memory-index-v2"
```

`upsert` 会保留旧文件，将旧状态改为 `superseded`，记录 `superseded_by`，并分别重建 `索引.md` 与 `历史索引.md`。

## 知识摘要

摘要正文必须简短列出当前有效知识，并让每个要点引用至少一个来源记录 ID。完成语义合并后写入：

```bash
python "<本 Skill目录>/scripts/memory_maintenance.py" \
  --vault-root "<Vault根目录>" \
  --project "<项目名称>" \
  write-summary \
  --body-file "<摘要正文>" \
  --source-id "<活跃记录ID>" \
  --coverage complete
```

工具默认限制为 6,000 字符、80 行，并保存全部活跃记录的输入指纹。只有确认摘要覆盖当前稳定知识时才设置 `--coverage complete`；范围有限的摘要保持默认 `partial`。任何活跃记录新增、更新或改变状态后，审计会把摘要标记为过期；摘要过期或覆盖不完整时，`project-memory` 回退到同样有硬上限的活跃索引，直到下一次维护重建摘要。

已处理或忽略超过 30 天的收件箱条目可先预览、再做可恢复归档：

```bash
python "<本 Skill目录>/scripts/memory_maintenance.py" \
  --vault-root "<Vault根目录>" \
  --project "<项目名称>" \
  archive-inbox --older-than-days 30
```

确认候选无误且当前任务授权整理写入时，追加 `--apply`。此命令只移动文件到 `收件箱/归档/<年份>/`，不删除。

## 分批与停止条件

- 每批最多 12 条候选，正文合计约 24,000 字符时继续拆批。
- 一批只处理一个 `type + module + 主题`。
- 任何来源冲突、适用范围不明或代码验证失败都应停止该主题的写入，并将其列为待复核项。
- 达到维护目标后停止；不要为追求更少记录继续合并有独立价值的事实。

## 定时运行提示词

为 Codex 自动化使用以下意图即可，不在 Skill 中固定调度频率：

> 使用 $project-memory-maintenance 维护当前项目知识库。先执行只读审计；仅在活跃索引超过建议范围、存在同主题冗余或状态链未收敛时，分批复核并合并。不得删除历史记录。完成后验证并报告前后指标；没有变化时直接结束。

通常每周或每两周运行一次即可；实际频率取决于记忆写入速度。创建自动化时由用户明确时区和运行时间。
