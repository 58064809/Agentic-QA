# 自然语言命令路由

Codex 接到自然语言命令后，先识别意图，再路由到对应 SOP 和 Workflow。

所有任务完成后的 Chat 回复必须遵守 `rules/codex-output-rules.md`：不粘贴完整大文件或完整 diff，只输出摘要、关键路径、验收结果和待人工确认项。
完成回执必须包含：变更摘要、修改文件、验收结果、待人工确认、下一步建议。

## 路由表

| 用户意图关键词 | Workflow | Task | Agent | Prompt | Rules | Skills/Knowledge | 输入 | 输出 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| 定位需求、找到 PRD | `workflows/01-requirement-analysis-workflow.md` | `tasks/00-locate-requirement.md` | Requirement Analysis Agent | `prompts/requirement-analysis-prompt.md` | `rules/naming-rules.md` | `prd/_registry.yml` | 用户命令、registry | 只读定位 | 不变更 |
| 分析需求、拆解需求 | `workflows/01-requirement-analysis-workflow.md` | `tasks/01-analyze-requirement.md` | Requirement Analysis Agent | `prompts/requirement-analysis-prompt.md` | `rules/requirement-analysis-rules.md` | `skills/requirement-decomposition-skill.md`、`skills/business-rule-extraction-skill.md` | `requirement.md`、`api-doc.md`、`metadata.yml` | `10-analysis/requirement-analysis.md` | `needs_human_review` |
| 生成测试用例、设计用例 | `workflows/02-testcase-generation-workflow.md` | `tasks/02-generate-testcases.md` | Testcase Design Agent | `prompts/testcase-design-prompt.md` | `rules/testcase-rules.md` | `skills/test-design-skill.md`、`knowledge/templates/testcase-template.md` | 已审核或待审需求分析 | `20-testcases/testcases.md` | `needs_human_review` |
| 生成 API 测试、接口自动化 | `workflows/03-api-test-generation-workflow.md` | `tasks/03-generate-api-tests.md` | API Test Generation Agent | `prompts/api-test-generation-prompt.md` | `rules/api-test-rules.md` | `skills/api-contract-analysis-skill.md`、`skills/pytest-api-test-skill.md` | 接口文档、测试用例 | `30-api-tests/api-test-plan.md`、`30-api-tests/generated/` | `needs_human_review` |
| 生成 UI 测试、端到端测试 | `workflows/04-ui-test-generation-workflow.md` | `tasks/04-generate-ui-tests.md` | UI Test Generation Agent | `prompts/ui-test-generation-prompt.md` | `rules/ui-test-rules.md` | `skills/playwright-ui-test-skill.md` | 需求、用例、页面入口 | `40-ui-tests/generated/` | `needs_human_review` |
| 执行测试、跑测试 | `workflows/05-test-execution-workflow.md` | `tasks/05-execute-tests.md` | Test Execution Agent | `prompts/test-execution-prompt.md` | `rules/test-execution-rules.md` | `scripts/run_pytest.py`、`scripts/collect_test_results.py` | 已审核脚本、执行环境 | `50-execution-results/` | `needs_human_confirmation` |
| 分析失败、看日志 | `workflows/06-failure-analysis-workflow.md` | `tasks/06-analyze-failures.md` | Failure Analysis Agent | `prompts/failure-analysis-prompt.md` | `rules/failure-analysis-rules.md` | `skills/failure-log-analysis-skill.md` | 执行结果、日志、用例 | `60-failure-analysis/failure-analysis.md` | `needs_human_confirmation` |
| 生成 bug、提缺陷 | `workflows/07-bug-draft-workflow.md` | `tasks/07-generate-bug-draft.md` | Bug Draft Agent | `prompts/bug-draft-prompt.md` | `rules/failure-analysis-rules.md` | `skills/bug-report-writing-skill.md` | 失败分析、证据 | `70-bugs/` | `needs_human_review` |
| 生成报告、QA 报告 | `workflows/08-report-generation-workflow.md` | `tasks/08-generate-report.md` | Report Generation Agent | `prompts/report-generation-prompt.md` | `rules/status-rules.md` | `skills/qa-report-writing-skill.md`、`knowledge/templates/qa-report-template.md` | 全部 QA 产物 | `80-reports/qa-report-draft.md` | `needs_human_confirmation` |
| 归档需求、完成归档 | `workflows/09-archive-workflow.md` | `tasks/09-archive-requirement.md` | Archive Agent | `prompts/archive-prompt.md` | `rules/archive-rules.md` | `scripts/archive_requirement.py` | metadata、正式报告、全部产物 | `90-archive/archive-index.md` | `archived` |

## 常见中文触发表达

- 需求分析：“分析这个需求”“拆一下登录需求”“帮我看 PRD”“提取业务规则”。
- 用例生成：“生成测试用例”“设计覆盖场景”“补边界用例”“列回归用例”。
- API 测试：“生成接口自动化”“写 pytest 草稿”“根据接口文档出测试脚本”。
- UI 测试：“生成 Playwright 脚本”“做端到端测试草稿”“覆盖登录页面流程”。
- 测试执行：“跑测试”“执行自动化”“收集 pytest 结果”。
- 失败分析：“看失败日志”“判断失败原因”“分类这些失败”。
- 缺陷草稿：“生成 bug 草稿”“整理缺陷报告”“把真实缺陷写成 issue”。
- QA 报告：“生成 QA 报告草稿”“汇总测试结果”“输出风险结论草稿”。
- 归档：“归档这个需求”“生成归档索引”“确认完成后归档”。

## 命令解析规则

- 若用户没有给出 PRD 工作区，先执行 `tasks/00-locate-requirement.md`。
- 需求名模糊时，先按 `prd/_registry.yml` 的 `requirement_id`、`title`、`path` 做包含匹配。
- 如果匹配到多个 PRD 候选，不得猜测；必须列出候选路径并等待用户确认。
- 如果没有匹配到 PRD，询问用户是否创建新工作区，或要求提供明确路径。
- 如果缺少前置产物，先生成缺失的上游草稿，或明确说明阻塞项。
- 若目标产物依赖未审核上游产物，必须停止并提示人工审核。
- 若命令包含“直接执行”“跑测试”，仍需检查执行环境、测试数据和风险。
- 若命令包含“归档”，必须先运行 `scripts/archive_requirement.py` 的审核状态检查。
- AI 生成的 QA 报告只能写入 `prd/<id>/80-reports/qa-report-draft.md`；人工确认后的正式报告可命名为 `qa-report.md`。
- 大段产物内容必须写入仓库文件，Chat 中只提供文件路径和摘要。
- 每个任务完成后必须输出标准回执，验收命令必须明确区分“通过 / 失败 / 未执行”。

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
