# 09 归档工作流

## 适用场景

用于在所有人工审核和确认完成后归档需求。

## 触发命令

- “归档 `prd/<id>`。”
- “确认完成后生成归档索引。”

## 主 Agent

Archive Agent

## 辅助 Agent

Report Generation Agent 提供报告状态，Test Execution Agent 提供执行结果状态。

## 必须读取

- `prompts/archive-prompt.md`
- `rules/archive-rules.md`
- `rules/status-rules.md`
- `scripts/archive_requirement.py`

## 输入文件

- `prd/<id>/metadata.yml`
- `prd/<id>/80-reports/qa-report.md`，人工确认后的正式报告。
- `prd/<id>/80-reports/qa-report-draft.md`，如正式报告尚未生成，则必须作为待确认草稿处理。
- 所有关联 QA 产物

## 输出路径

- `prd/<id>/90-archive/archive-index.md`

## 执行步骤

1. 运行 PRD 工作区结构校验。
2. 检查 metadata 中是否存在未审核或未确认状态。
3. 若存在阻塞状态，停止并说明阻塞项。
4. 若全部通过，生成归档索引。
5. 更新 metadata 状态为 `archived`。

## 前置条件

- metadata、正式 QA 报告和关键 QA 产物存在。
- 所有 review gate 已由人工确认。
- `archive_requirement.py` 检查通过。

## 状态标记

- 阻塞时不得改状态。
- 归档成功后 metadata 可标记为 `archived`。

## 异常处理

- 只有 `qa-report-draft.md` 而没有正式报告时，停止归档。
- 存在 `needs_human_review` 或 `needs_human_confirmation` 时，输出阻塞项。
- 归档脚本失败时，不手工创建归档索引。

## 禁止事项

- 不绕过 `needs_human_review` 或 `needs_human_confirmation`。
- 不删除原始产物。
- 不伪造审核通过状态。

## 验收标准

- 归档索引存在且列出关键产物。
- metadata 状态合法。

## 人工审核点

- 是否允许正式归档。
- 归档前产物是否完整。
