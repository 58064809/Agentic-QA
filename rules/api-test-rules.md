# API 测试规则

- API 测试必须基于已审核接口文档和测试用例。
- 请求、响应、状态码、错误码、鉴权和幂等要求必须明确。
- 禁止在脚本中硬编码真实账号、密码、token 或生产地址。
- 断言必须覆盖状态码、响应结构、关键字段和业务错误码。
- 对破坏性接口必须标注执行风险和数据清理策略。

## 生成标准

- 每个接口测试脚本必须声明 `base_url`、认证方式、测试数据来源和跳过条件。
- 默认不请求真实服务；没有 `LOGIN_API_BASE_URL` 等显式环境变量时必须 skip。
- 断言必须区分 HTTP 状态码、业务码、响应字段、错误消息和状态副作用。
- 对登录、支付、账号锁定等状态接口，必须说明如何隔离测试账号和重置状态。
- API 文档缺失字段时，脚本只能生成草稿，并在测试计划中列出待确认项。
- API 测试草稿必须先写入 `runs/<run_id>/artifact-preview.md` 作为人类可读候选预览；YAML 接口用例草稿写入同一运行目录的 `runs/<run_id>/api-test-cases.yml` 作为 sidecar。
- YAML sidecar 跟随 `reviews/api-test-draft.review.yml` 审核；Review Gate 通过并 promote 后才允许写入 `artifacts/api-test-cases.yml`。
- YAML 用例不得包含完整域名、生产地址、真实 token、Cookie、账号或密码。
- 现有 pytest 执行入口只能在显式设置 `AGENTIC_QA_API_CASES_FILE` 和 `AGENTIC_QA_BASE_URL` 后读取 YAML 执行。
