# QA 产物标准

Agentic-QA 的产物统一写入需求工作区的 `artifacts/` 目录，并通过 `reviews/` 记录确认状态，通过 `runs/` 追踪生成过程。

## 产物类型

| 产物 | 路径 | 说明 |
|---|---|---|
| 需求分析 | `artifacts/requirement-analysis.md` | 对需求背景、业务规则、流程、风险和测试范围的结构化分析 |
| 测试用例 | `artifacts/testcases.md` | 面向评审、执行、自动化生成和知识沉淀的结构化测试用例 |
| 接口测试草稿 | `artifacts/api-test-draft.md` | 接口测试计划、断言点、数据准备或脚本草稿 |
| UI 测试草稿 | `artifacts/ui-test-draft.md` | UI 测试路径、页面对象、断言点或脚本草稿 |
| 执行报告 | `artifacts/execution-report.md` | 测试执行结果、通过率、失败项和环境信息 |
| 失败分析 | `artifacts/failure-analysis.md` | 对失败用例、日志、环境和缺陷可能性的分析 |
| Bug 草稿 | `artifacts/bug-draft.md` | 可复制到缺陷系统的 Bug 标题、步骤、实际结果和预期结果 |
| QA 报告 | `artifacts/qa-report.md` | 需求质量、测试范围、执行结论、风险和遗留问题汇总 |
| 归档索引 | `artifacts/archive-index.md` | 当前需求的输入、产物、确认状态和运行记录索引 |

## 产物元数据

AI 生成产物必须包含 Front Matter，用于标记产物类型、状态、来源和确认要求。

```yaml
---
artifact_type: testcases
status: needs_human_review
human_review_required: true
source_requirement: input/requirement.md
source_api: input/api.md
generated_by: agentic-qa-runtime
run_id: ""
created_at: ""
updated_at: ""
---
```

## 产物状态

| 状态 | 含义 |
|---|---|
| `draft` | 草稿生成中或尚未进入确认 |
| `partial` | 只生成部分内容，不能作为正式产物 |
| `needs_human_review` | 等待用户通过 Chat / Bot / CLI 确认 |
| `approved` | 已确认通过，可进入下一步 |
| `needs_changes` | 需要修订后重新确认 |
| `rejected` | 当前产物不可用，需要重新生成或废弃 |
| `confirmed` | 已完成最终确认，可作为正式测试资产 |
| `archived` | 已归档 |
| `failed` | 生成失败，仅保留错误上下文和中间结果 |
| `superseded` | 已被新版本产物替代 |
