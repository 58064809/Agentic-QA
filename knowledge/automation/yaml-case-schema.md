# YAML 接口用例 Schema

## 目标

定义 RAG 生成接口自动化用例草稿的最小 YAML 结构。该结构用于人工审核和后续 pytest 执行框架消费。

## 顶层结构

```yaml
schema_version: v1
artifact_type: api_automation_cases
status: needs_human_review
human_review_required: true
generated_from:
  workflow: workflows/10-rag-automation-case-generation-workflow.md
  prompt: prompts/rag-automation-case-prompt.md
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
| `schema_version` | Schema 版本，第一版为 `v1` |
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
