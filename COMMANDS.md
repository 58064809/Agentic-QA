# 自然语言命令路由

Codex 接到自然语言命令后，先识别意图，再路由到对应 SOP 和 Workflow。

## 路由表

| 用户意图关键词 | 路由任务 | Workflow | 主 Agent | 输出目录 |
|---|---|---|---|---|
| 定位需求、找到 PRD | `tasks/00-locate-requirement.md` | `workflows/01-requirement-analysis-workflow.md` | Requirement Analysis Agent | 只读定位 |
| 分析需求、拆解需求 | `tasks/01-analyze-requirement.md` | `workflows/01-requirement-analysis-workflow.md` | Requirement Analysis Agent | `10-analysis/` |
| 生成测试用例、设计用例 | `tasks/02-generate-testcases.md` | `workflows/02-testcase-generation-workflow.md` | Testcase Design Agent | `20-testcases/` |
| 生成 API 测试、接口自动化 | `tasks/03-generate-api-tests.md` | `workflows/03-api-test-generation-workflow.md` | API Test Generation Agent | `30-api-tests/generated/` |
| 生成 UI 测试、端到端测试 | `tasks/04-generate-ui-tests.md` | `workflows/04-ui-test-generation-workflow.md` | UI Test Generation Agent | `40-ui-tests/generated/` |
| 执行测试、跑测试 | `tasks/05-execute-tests.md` | `workflows/05-test-execution-workflow.md` | Test Execution Agent | `50-execution-results/` |
| 分析失败、看日志 | `tasks/06-analyze-failures.md` | `workflows/06-failure-analysis-workflow.md` | Failure Analysis Agent | `60-failure-analysis/` |
| 生成 bug、提缺陷 | `tasks/07-generate-bug-draft.md` | `workflows/07-bug-draft-workflow.md` | Bug Draft Agent | `70-bugs/` |
| 生成报告、QA 报告 | `tasks/08-generate-report.md` | `workflows/08-report-generation-workflow.md` | Report Generation Agent | `80-reports/qa-report-draft.md` |
| 归档需求、完成归档 | `tasks/09-archive-requirement.md` | `workflows/09-archive-workflow.md` | Archive Agent | `90-archive/` |

## 命令解析规则

- 若用户没有给出 PRD 工作区，先执行 `tasks/00-locate-requirement.md`。
- 若目标产物依赖未审核上游产物，必须停止并提示人工审核。
- 若命令包含“直接执行”“跑测试”，仍需检查执行环境、测试数据和风险。
- 若命令包含“归档”，必须先运行 `scripts/archive_requirement.py` 的审核状态检查。
- AI 生成的 QA 报告只能写入 `prd/<id>/80-reports/qa-report-draft.md`；人工确认后的正式报告可命名为 `qa-report.md`。

## 推荐命令格式

```text
请对 prd/sample-login-requirement 执行需求分析，并生成 10-analysis/requirement-analysis.md，等待我审核。
```

```text
基于已审核用例，为 prd/sample-login-requirement 生成 pytest API 测试草稿。
```

```text
执行 prd/sample-login-requirement 的测试，收集结果并生成 QA 报告草稿。
```
