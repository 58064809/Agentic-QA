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
- 报告生成时间：2026-05-09T01:15:59+00:00
- 正式报告路径：prd/sample-login-requirement/80-reports/qa-report.md
- 当前报告不得作为正式发布结论。

## 需求与分析摘要

---
status: needs_human_review
human_review_required: true
artifact_type: requirement_analysis_draft
generated_by: Codex
---

# 手机号密码登录需求分析草稿

## 需求摘要

本需求描述用户通过手机号和密码登录系统。系统需要校验手机号格式、密码正确性、连续错误次数、账号锁定状态和 token 过期状态。登录成功后返回 token；token 过期后访问受保护资源需要重新登录。

## 业务规则

| 编号 | 规则 | 来源 | 状态 |
|---|---|---|---|
| R1 | 用户使用手机号和密码登录 | `requirement.md` | 待人工审核 |
| R2 | 手机号格式必须符合中国大陆手机号格式 | `requirement.md`、`api-doc.md` | 待人工审核 |
| R3 | 密码错误时提示“手机号或密码错误” | `requirement.md`、`api-doc.md` | 待人工审核 |
| R4 | 同一账号连续输错 5 次后锁定 15 分钟 | `requirement.md` | 待人工审核 |
| R5 | 锁定期间再次登录提示账号锁定并返回剩余锁定时间 | `requirement.md` | 待人工确认 |
| R6 | 登录成功返回 access token、token 类型和过期时间 | `requirement.md`、`api-doc.md` | 待人工审核 |
| R7 | token 过期后访问受保护资源提示重新登录 | `requirement.md`、`api-doc.md` | 待人工审核 |

## 用户流程

1. 用户进入登录入口。
2. 用户输入手机号和密码。
3. 系统校验手机号格式。
4. 系统校验账号状态和密码。
5. 登录成功时返回 token。
6. 后续访问受保护资源时校验 token。
7. token 过期后要求用户重新登录。

## 数据规则

| 数据 | 规则 | 待确认点 |
|---|---|---|
| phone | 中国大陆手机号格式 | 是否限定具体号段 |
| password | 由服务端验证，接口文档未定义复杂度 | 是否需要密码复杂度错误提示 |
| error_count | 连续错误次数达到 5 次触发锁定 | 计数维度是账号、手机号、设备还是 IP |
| lock_until | 锁定 15 分钟 | 是否返回剩余秒数 |
| access_token | 登录成功返回 | token 有效期是否固定 7200 秒 |

## 权限/状态规则

| 状态 | 允许动作 | 禁止动作 | 预期响应 |

## 测试用例摘要

---
status: needs_human_review
human_review_required: true
artifact_type: testcase_draft
generated_by: Codex
---

# 手机号密码登录测试用例草稿

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
| 手机号密码登录成功返回 token | P0 | 用户存在、未锁定、密码正确 | 1. 调用登录接口<br>2. 输入合法手机号和正确密码 | 返回成功响应，包含 access_token、token_type、expires_in |
| 手机号格式错误时拒绝登录 | P1 | 无 | 1. 输入 `12345` 作为手机号<br>2. 输入任意密码提交 | 返回 `INVALID_PHONE` 或手机号格式错误提示 |
| 密码错误但未达锁定阈值 | P0 | 用户存在且错误次数为 0 | 1. 输入合法手机号<br>2. 输入错误密码提交 | 返回 `INVALID_CREDENTIALS`，不返回 token |
| 连续第 4 次密码错误仍未锁定 | P0 | 同一账号已连续输错 3 次 | 1. 再次输入错误密码<br>2. 查询响应 | 返回密码错误提示，账号未锁定 |
| 连续第 5 次密码错误触发锁定 | P0 | 同一账号已连续输错 4 次 | 1. 再次输入错误密码<br>2. 查询响应 | 返回账号锁定提示，锁定 15 分钟 |
| 锁定期间再次登录被拒绝 | P0 | 账号处于锁定中 | 1. 输入正确密码登录 | 返回 `ACCOUNT_LOCKED`，不返回 token |
| 锁定期结束后允许重新登录 | P1 | 账号锁定已超过 15 分钟 | 1. 输入正确密码登录 | 登录成功并返回 token |
| token 过期后访问受保护资源 | P0 | 已持有过期 token | 1. 使用过期 token 访问 `/api/v1/profile` | 返回 `TOKEN_EXPIRED`，提示重新登录 |
| 未携带 token 访问受保护资源 | P1 | 用户未登录 | 1. 不带 Authorization 访问 `/api/v1/profile` | 返回未认证或重新登录提示 |
| 错误响应不泄露账号存在性 | P1 | 使用不存在手机号或错误密码 | 1. 分别提交不存在手机号和错误密码 | 错误文案不暴露账号是否存在 |

## 覆盖说明

- 正常流程：登录成功。
- 异常流程：手机号格式错误、密码错误、未认证访问。
- 边界值：第 4 次、第 5 次、第 6 次锁定相关行为。
- 状态流转：正常、错误计数中、锁定中、锁定解除、tok

## 执行结果摘要

---
status: needs_human_confirmation
human_confirmation_required: true
artifact_type: execution_report_draft
generated_by: Codex
---

# 测试执行报告草稿

## 执行说明

本报告记录仓库级本地验收命令和示例 API 草稿脚本的执行约束，不代表真实业务接口测试结论。

## 已执行的本地命令

| 命令 | 结果 | 说明 |
|---|---|---|
| `python scripts/validate_prd_workspace.py prd/sample-login-requirement` | 通过 | 校验 PRD 工作区结构 |
| `python scripts/run_pytest.py` | 通过 | 执行仓库单元测试并生成 pytest json 报告 |
| `pytest` | 通过 | 执行仓库单元测试 |
| `ruff check .` | 通过 | 执行静态检查 |

## 未执行的真实业务接口测试

`30-api-tests/generated/test_login_api.py` 默认需要 `LOGIN_API_BASE_URL`。当前仓库不提供真实服务地址，也不允许默认连接生产环境，因此示例 API 脚本默认 skip。

## 待人工确认

- [ ] 是否提供授权的非生产环境。
- [ ] 是否提供测试账号和数据恢复方式。
- [ ] 是否允许执行 API 草稿脚本。

## 失败分析摘要

---
status: needs_human_confirmation
human_confirmation_required: true
artifact_type: failure_analysis_draft
generated_by: Codex
---

# 失败分析草稿

暂无真实失败日志，以下为示例分析框架。

## 失败分类框架

| 失败项 | 现象 | 分类 | 证据 | 下一步 |
|---|---|---|---|---|
| API 脚本默认 skip | 未设置 `LOGIN_API_BASE_URL` 时不请求服务 | 环境问题 | pytest skip 原因 | 提供授权测试环境后执行 |
| 登录成功断言失败 | 响应缺少 token 字段 | 暂无法判断 | 需真实响应日志 | 核对接口文档和实现 |
| 密码错误响应不一致 | 状态码或业务码与文档不一致 | 接口文档不一致 | 需真实响应日志 | 接口负责人确认契约 |

## 固定失败分类

- 真实缺陷
- 脚本问题
- 环境问题
- 测试数据问题
- 需求不清
- 预期错误
- 接口文档不一致
- 偶现问题
- 暂无法判断

## 待人工确认

- [ ] 是否已有真实失败日志需要补充。
- [ ] 是否有授权环境可以执行 API 草稿脚本。
- [ ] 接口响应契约是否与 `api-doc.md` 一致。

## 结论草稿

- 当前报告由脚本生成，结论必须经过人工确认。
- 若存在未审核或未确认状态，不允许归档。

## 待人工确认

- 需求理解是否准确。
- 用例覆盖是否充分。
- 自动化结果是否可信。
- 缺陷判断和发布建议是否可接受。
