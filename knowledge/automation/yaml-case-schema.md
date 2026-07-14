# YAML 接口用例 Schema

本文件定义 RAG 接口自动化 YAML 的当前机器契约。Validator 实现位于 `runtime/validators/api_case_contract_rules.py`，字段定义不得与其漂移。

## 流转

```text
runs/<run-id>/api-test-draft.preview.md
runs/<run-id>/api-test-cases.yml
reviews/api-test-draft.review.yml
artifacts/api-test-draft.md
artifacts/api-test-cases.yml
```

YAML 是 `api_test_draft` 的机器可消费 sidecar。候选必须与 Markdown 草稿共用同一 run 和 Review Gate；`artifacts/api-test-cases.yml` 只能由 promote 写入。

## 顶层结构

```yaml
schema_version: agentic-qa.api-cases.v1
artifact_type: api_automation_cases
status: needs_human_review
human_review_required: true
generated_from:
  workflow: workflows/runtime/rag-automation-case.workflow.yml
  prompt: prompts/rag-automation-case-prompt.md
  rag_run_record: rag/run_records/<run-id>.json
source_refs:
  - source_type: prd
    source_path: prd/<id>/input/requirement.md
    chunk_id: prd-login-rule-001
    locator: 登录规则章节
    summary: 登录成功后返回访问令牌
    confidence: high
cases:
  - id: API-001
    title: 正确账号密码登录成功返回访问令牌
    priority: P0
    review_status: needs_human_review
    source_refs:
      - source_type: openapi
        source_path: knowledge/api/auth/openapi.json
        chunk_id: openapi-post-login
        locator: POST /api/auth/login
        summary: 登录接口请求和响应结构
        confidence: high
    request:
      method: POST
      path: /api/auth/login
      headers:
        Content-Type: application/json
      query: {}
      body:
        username: ${TEST_LOGIN_USERNAME}
        password: ${TEST_LOGIN_PASSWORD}
    assertions:
      - type: status_code
        expected: 200
      - type: json_field_exists
        path: $.data.access_token
    variables:
      extract:
        access_token: $.data.access_token
      env:
        - TEST_LOGIN_USERNAME
        - TEST_LOGIN_PASSWORD
    cleanup: []
review_questions:
  - 登录失败错误码需与已确认接口契约核对。
```

## 字段约束

| 字段 | 约束 |
|---|---|
| `schema_version` | 固定为 `agentic-qa.api-cases.v1` |
| `artifact_type` | 固定为 `api_automation_cases` |
| `status` | 候选固定为 `needs_human_review` |
| `human_review_required` | 候选固定为 `true` |
| `generated_from.workflow` | 当前 Runtime Workflow YAML |
| `source_refs` | 顶层来源汇总 |
| `cases` | 用例列表 |
| `review_questions` | 所有契约缺口和人工判断项 |

每条 case 至少包含：

- `id`
- `title`
- `priority`
- `review_status`
- 非空 `source_refs`
- `request`
- `assertions`
- `variables`
- `cleanup`

## 来源与置信度

- 已确认 OpenAPI operation 明确命中 method + path 时可使用 `high`。
- 仅依赖需求关键词、summary、tags 或模糊检索时不得高于 `medium`。
- 历史经验只能作为风险来源，不得作为接口契约来源。

## 契约缺失

缺少已确认接口契约时：

- 不得根据需求、历史经验或常识编造 method、path、请求字段、响应字段、错误码或鉴权方式。
- `request` 保持空对象，或只包含明确有来源的字段。
- 所有缺口写入 `review_questions`。
- 不得为了满足覆盖数量生成虚假断言。

## 安全

YAML 不得包含真实 Token、Cookie、密码、手机号、身份证、银行卡、密钥或完整生产域名。敏感值只能使用环境变量、fixture 或 case 变量引用。
