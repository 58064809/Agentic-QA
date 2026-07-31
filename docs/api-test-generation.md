# API 测试契约

当测试目标包含 API 时，`api_test_draft` 提供可审核、可发布和可执行的机器用例。Candidate 与
published 文件均为 YAML，数据契约是 `agentic-qa.api-cases.v1.1`。

## 场景

| 来源 | endpoint 事实 | 可生成内容 | 系统标记 |
|---|---|---|---|
| SourceBundle 中完整且成功解析的 OpenAPI 3.x/Swagger 2.0 | confirmed | method/path、参数、请求体、响应、安全定义和契约断言 | high-confidence source ref |
| 残缺或解析失败的 OpenAPI | partial/missing | 缺口与待确认草案 | 解析问题 |
| Markdown/PRD | 不构成协议事实 | 业务场景、规则候选 | 待确认 endpoint |
| [API Discovery 抓包](api-discovery.md) / 示例请求 | 作为观察样本 | 候选接口与复现线索 | observed / 非完整契约 |

## 操作与系统响应

启动 run 时选择 `api_test_draft`。系统先冻结 `sources/`，再由 `openapi.inspect` 归一化契约。
模型返回强类型 `AgentOutput.api_test_cases`，Harness 校验业务规则引用、endpoint 与 OpenAPI
证据，并稳定渲染为 `candidates/<run_id>/api_test_draft/raw.yml`。

无完整契约时，系统仍可生成 `missing`、`pending_confirmation` 或 `partial` 用例；这些用例的
method/path 为 `null`。模型直接声称一个未出现在本次 OpenAPI 检查结果中的 confirmed
endpoint 时，artifact validation 返回错误并进入修订循环。

Candidate 停在人工 Review Gate。人工选择通过质量门的版本后，发布文件位于：

```text
workspaces/<workspace>/published/api_test_draft/current.yml
```

`api.execute` 读取这份 published YAML，并继续受 ExecutionProfile、workspace policy、环境变量和
HTTP method allowlist 控制。请求位于 `request.method/path`，断言位于类型化 `assertions`。
workspace 环境可以选择静态 token 或执行前登录取 token；认证头由执行器统一注入，不改变
API Cases v1.1 文件。

## 示例

```yaml
schema_version: agentic-qa.api-cases.v1.1
artifact_type: api_automation_cases
status: needs_human_review
human_review_required: true
base_url_env: AGENTIC_QA_BASE_URL
business_rules:
  - RULE-001
source_refs:
  - source_type: openapi
    source_path: sources/openapi.yml
    chunk_id: post-assist
    locator: POST /assist
    summary: 提交助力
    confidence: high
cases:
  - id: API-001
    title: 提交有效助力
    priority: P0
    contract_status: confirmed
    business_rule_refs: [RULE-001]
    review_status: needs_human_review
    review_questions: [测试账号与数据由人工选择]
    source_refs:
      - source_type: openapi
        source_path: sources/openapi.yml
        chunk_id: post-assist
        locator: POST /assist
        summary: 提交助力
        confidence: high
    pending: []
    request:
      method: POST
      path: /assist
      headers: {}
      query: {}
      body: {}
    assertions:
      - type: status_code
        expected: [200]
        path: null
    variables: {}
    cleanup: []
review_questions:
  - 测试环境和数据由人工确认
```

完整字段约束见机器可读 [API Cases JSON Schema](schemas/api-cases.v1.1.schema.json)。

## 常见问题

| 现象 | 系统行为 |
|---|---|
| 只有 PRD，没有 OpenAPI | 生成待确认场景，不确认 method/path |
| OpenAPI 使用外部 `$ref` | 检查返回不支持外部引用；来源先整合为自包含契约 |
| Candidate 已生成但执行工具拒绝 | `api.execute` 只读取人工审核后发布的 YAML |
| 环境名称类似 production | ExecutionProfile 校验返回错误 |
| POST 未在 allowlist | 执行证据记录为 blocked，不发送请求 |
| 静态 token 环境变量为空 | `api.execute` 返回认证配置错误，不发送用例请求 |
| 登录状态码或 token JSON 路径不匹配 | `api.execute` 返回认证错误，不发送后续用例请求 |
| 请求或响应失败 | 证据记录 error/failed，不自动生成已确认 Bug |
