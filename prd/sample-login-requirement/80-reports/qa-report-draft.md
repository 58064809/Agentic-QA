---
status: needs_human_confirmation
human_confirmation_required: true
artifact_type: qa_report_draft
generated_by: scripts/generate_markdown_report.py
---

# QA 报告草稿：手机号密码登录

## 基本信息

- 需求 ID：sample-login-requirement
- 当前状态：draft
- 负责人：QA Owner
- 报告生成时间：2026-05-09T02:48:03+00:00
- 正式报告路径：prd/sample-login-requirement/80-reports/qa-report.md
- 当前报告不得作为正式发布结论。

## 产物索引

| 产物 | 路径 | 当前状态 |
|---|---|---|
| requirement | `prd/sample-login-requirement/requirement.md` | 存在 |
| api_doc | `prd/sample-login-requirement/api-doc.md` | 存在 |
| analysis | `prd/sample-login-requirement/10-analysis/requirement-analysis.md` | 存在 |
| testcases | `prd/sample-login-requirement/20-testcases/testcases.md` | 存在 |
| api_test_plan | `prd/sample-login-requirement/30-api-tests/api-test-plan.md` | 存在 |
| api_tests | `prd/sample-login-requirement/30-api-tests/generated/` | 存在 |
| ui_tests | `prd/sample-login-requirement/40-ui-tests/generated/` | 存在 |
| execution_results | `prd/sample-login-requirement/50-execution-results/` | 存在 |
| execution_report | `prd/sample-login-requirement/50-execution-results/execution-report.md` | 存在 |
| failure_analysis | `prd/sample-login-requirement/60-failure-analysis/failure-analysis.md` | 存在 |
| bugs | `prd/sample-login-requirement/70-bugs/` | 存在 |
| report_draft | `prd/sample-login-requirement/80-reports/qa-report-draft.md` | 存在 |
| report | `prd/sample-login-requirement/80-reports/qa-report.md` | 待生成 |
| archive | `prd/sample-login-requirement/90-archive/` | 存在 |

## 需求分析摘要

- 本需求描述用户通过手机号和密码登录系统。系统需要校验手机号格式、密码正确性、连续错误次数、账号锁定状态和 token 过期状态。登录成功后返回 token；token 过期后访问受保护资源需要重新登录。
- 已识别业务规则 7 条。

## 测试用例摘要

- 已识别测试用例 10 条。
- 优先级分布：P0 6 条、P1 4 条。
- 代表性用例：手机号密码登录成功返回 token；手机号格式错误时拒绝登录；密码错误但未达锁定阈值；连续第 4 次密码错误仍未锁定；连续第 5 次密码错误触发锁定。
- 完整用例请查看 `20-testcases/testcases.md`。

## 自动化与执行摘要

- 已记录本地验收命令 4 条，通过 4 条。
- 真实业务接口测试是否执行需以授权环境和执行报告为准。
- 未执行说明：`30-api-tests/generated/test_login_api.py` 默认需要 `LOGIN_API_BASE_URL`。当前仓库不提供真实服务地址，也不允许默认连接生产环境，因此示例 API 脚本默认 skip。

## 失败分析摘要

- 已记录失败分类示例 3 条。
- 暂无真实失败日志，以下为示例分析框架。
- 真实缺陷结论必须等待人工确认和真实失败证据。

## 风险与阻塞项

- metadata 中仍存在待审核或待确认状态时，不允许归档。
- 未提供授权非生产环境前，不应把示例 API 脚本结果作为真实业务测试结论。
- 当前报告只提供摘要和产物索引，完整证据需通过上方路径人工查看。

## 待人工确认项

- 需求分析审核：needs_human_review，负责人 产品负责人。
- 测试用例审核：needs_human_review，负责人 QA 负责人。
- 执行前确认：needs_human_confirmation，负责人 QA 负责人。
- 执行结果确认：needs_human_confirmation，负责人 QA 负责人。
- 20-testcases/testcases.md：锁定计数维度是否符合产品和安全要求。
- 20-testcases/testcases.md：token 过期和刷新策略是否另有需求。
- 20-testcases/testcases.md：是否允许基于本用例生成自动化草稿。
- 30-api-tests/api-test-plan.md：错误响应是否使用 HTTP 状态码还是统一 HTTP 200。
- 30-api-tests/api-test-plan.md：锁定剩余时间字段名。
- 30-api-tests/api-test-plan.md：token 有效期和 refresh 机制。
- 50-execution-results/execution-report.md：是否提供授权的非生产环境。
- 正式 `qa-report.md` 只能在人工确认后生成。

## 结论草稿

- 当前报告由脚本生成，结论必须经过人工确认。
- 若存在未审核或未确认状态，不允许归档。
- 当前报告不得作为正式发布结论。
