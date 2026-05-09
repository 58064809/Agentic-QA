# 产物路径规则

所有 QA 产物必须写入对应 PRD 工作区，路径以 `prd/<requirement_id>/` 为根。

## 固定路径

| 产物 | 路径 |
|---|---|
| 原始需求 | `prd/<id>/requirement.md` |
| 接口文档 | `prd/<id>/api-doc.md` |
| 元数据 | `prd/<id>/metadata.yml` |
| 需求分析 | `prd/<id>/10-analysis/requirement-analysis.md` |
| 测试用例 | `prd/<id>/20-testcases/testcases.md` |
| API 测试计划 | `prd/<id>/30-api-tests/api-test-plan.md` |
| API 测试脚本 | `prd/<id>/30-api-tests/generated/` |
| UI 测试脚本 | `prd/<id>/40-ui-tests/generated/` |
| 执行结果 | `prd/<id>/50-execution-results/` |
| 执行报告 | `prd/<id>/50-execution-results/execution-report.md` |
| 失败分析 | `prd/<id>/60-failure-analysis/failure-analysis.md` |
| 缺陷草稿 | `prd/<id>/70-bugs/` |
| AI 生成 QA 报告草稿 | `prd/<id>/80-reports/qa-report-draft.md` |
| 人工确认正式 QA 报告 | `prd/<id>/80-reports/qa-report.md` |
| 归档索引 | `prd/<id>/90-archive/archive-index.md` |

## 规则

- 不允许把同一需求的产物散落在仓库根目录。
- 不允许覆盖人工已确认产物；需要修改时生成修订记录。
- 自动化脚本必须放入 `generated/`，人工维护脚本可另建 `manual/`。
- AI 只能生成 `qa-report-draft.md`；`qa-report.md` 是人工确认后的正式报告，可后续生成。
