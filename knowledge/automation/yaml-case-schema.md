# YAML 接口用例 Schema

## 目标

定义 RAG 生成接口自动化用例草稿的最小 YAML 结构。该结构用于人工审核和后续 pytest 执行框架消费。

YAML 用例文件是 `api_test_draft` 的机器可消费 sidecar 候选产物，不是独立绕过 Review Gate 的正式资产。固定流转为：

```text
runs/<run_id>/artifact-preview.md
runs/<run_id>/api-test-cases.yml
reviews/api-test-draft.review.yml
artifacts/api-test-cases.yml
```

其中 `artifacts/api-test-cases.yml` 只能在 Review Gate 通过并执行 promote 后写入。

## 顶层结构

```yaml
schema_version: agentic-qa.api-cases.v1.1
artifact_type: api_automation_cases
status: needs_human_review
human_review_required: true
base_url_env: AGENTIC_QA_BASE_URL
generated_from:
  workflow: workflows/runtime/rag-automation-case.workflow.yml
  prompt: prompts/api-test-generation.md
  rag_run_record: rag/run_records/<run_id>.json
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
      - source_type: swagger
        source_path: knowledge/api/auth-openapi.yaml
        chunk_id: swagger-post-login
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
      - type: json_field_type
        path: $.data.access_token
        expected: string
    variables:
      extract:
        access_token: $.data.access_token
      env:
        - TEST_LOGIN_USERNAME
        - TEST_LOGIN_PASSWORD
    cleanup: []
review_questions:
  - 登录失败错误码需与 Swagger / Apifox 核对。
```

## 字段说明

| 字段 | 说明 |
|---|---|
| `schema_version` | 当前 Schema 版本固定为 `agentic-qa.api-cases.v1.1` |
| `artifact_type` | 固定为 `api_automation_cases` |
| `status` | 默认 `needs_human_review` |
| `source_refs` | 顶层来源汇总 |
| `cases` | 用例列表 |
| `review_questions` | 待人工确认项 |

## 用例字段说明

| 字段 | 说明 |
|---|---|
| `id` | 用例 ID |
| `title` | 明确描述业务行为和预期 |
| `priority` | `P0`、`P1`、`P2`、`P3` |
| `review_status` | 默认 `needs_human_review` |
| `source_refs` | 用例级来源引用，不能为空 |
| `request` | 请求定义 |
| `assertions` | 断言列表 |
| `variables` | 环境变量、提取变量和 fixture 变量 |
| `cleanup` | 清理动作说明 |

禁止继续生成旧 v1 的顶层 `method`、`path` 和 `expected`。执行器仅为历史资产保留
`agentic-qa.api-cases.v1` 读取兼容；所有新候选必须通过 v1.1 质量门。

## contract_status

| 状态 | 允许的接口事实 |
|---|---|
| `missing` | `request: {}`、`assertions: []`，只记录契约缺口 |
| `pending_confirmation` | 仅记录抓包发现的 `request.method/path`，不得写确定性断言 |
| `partial` | 记录接口文档明确给出的 method/path/字段；未知字段和状态码不得补全 |
| `confirmed` | 来自 OpenAPI/Swagger/Apifox operation，且至少有可追溯的状态码断言 |

## 接口契约缺失约束

`request.method`、`request.path`、请求字段、响应字段、错误码和鉴权方式必须来自 Swagger / OpenAPI / Apifox 或已确认接口契约。

缺少接口契约时：

- 不得根据 PRD、历史经验或常识编造 `request.method`、`request.path`、请求字段或响应字段。
- 只能生成 `status: needs_human_review`、`review_status: needs_human_review` 的待确认草稿。
- `request` 应为空对象或仅包含明确来源字段。
- 接口契约缺口必须写入 `review_questions`。
