# 接口自动化 YAML 用例规则

## 状态规则

- AI 生成的 YAML 接口用例默认 `status: needs_human_review`。
- 每条用例的 `review_status` 默认 `needs_human_review`。
- 未经人工确认的 YAML 不得作为正式自动化资产执行。
- 人工确认前允许覆盖候选草稿，但必须保留 RAG 运行记录。

## 必填字段

YAML 顶层必须包含：

- `schema_version`
- `artifact_type`
- `status`
- `human_review_required`
- `generated_from`
- `source_refs`
- `cases`
- `review_questions`

新生成 YAML 固定使用 `agentic-qa.api-cases.v1.1`。method/path 位于 `request`，
断言位于 `assertions`；禁止生成旧版顶层 `method/path` 和 `expected`。

每条 `cases` 必须包含：

- `id`
- `title`
- `priority`
- `source_refs`
- `request`
- `assertions`
- `variables`
- `review_status`

## 安全规则

- `request.path` 只能写相对路径。
- 不得写完整生产域名。
- 不得写真实 token、Cookie、密码、手机号、身份证、银行卡或密钥。
- 动态值使用 `${ENV_NAME}`、`${case.variable}` 或 fixture 变量。
- 没有明确授权环境和账号时，不得执行真实请求。

## 接口契约规则

- 支持 Apifox 导出的服务级 OpenAPI JSON 接口契约库，默认路径为 `knowledge/api/<service>/openapi.json`。
- RAG 生成接口自动化 YAML 前必须先解析服务级 OpenAPI，按 operation 生成 chunk，并根据 `prd/<id>/input/api-scope.md` 精准召回；不得把完整服务级 OpenAPI 直接塞进 Prompt。
- `api-scope.md` 指定 `service` 和具体 `method path` 时，只允许使用命中的 OpenAPI operation；指定接口未命中时必须按缺失契约处理。
- 命中服务级 OpenAPI 时，`source_refs.source_type` 必须为 `openapi`，`source_refs.source_path` 指向对应 `knowledge/api/<service>/openapi.json`，`contract_status` 为 `confirmed`，`confidence` 可为 `high`。
- 只有 method/path 可确认、字段或响应状态码不完整时，`contract_status` 必须为 `partial`，不得为了满足断言数量而编造状态码。
- `request.method`、`request.path`、请求字段、响应字段、错误码和鉴权方式必须来自 Swagger / OpenAPI / Apifox 或已确认接口契约。
- 缺少 Swagger / OpenAPI / Apifox 接口契约时，不得根据 PRD、历史经验或常识编造接口事实。
- 接口契约缺失时只能生成 `needs_human_review` 待确认草稿，`request` 应为空对象或仅包含明确来源字段，并必须在 `review_questions` 中列出需要补充的接口契约。
- `runs/<run_id>/api-test-cases.yml` 是 `api_test_draft` 的 sidecar 候选产物；Review Gate 通过并 promote 前不得写入或覆盖 `artifacts/api-test-cases.yml`。

## 断言规则

- 至少包含 HTTP 状态码断言。
- 有业务码时必须包含业务码断言。
- 有响应体时必须包含关键字段存在性和类型断言。
- 涉及状态流转、库存、金额、次数、权限或幂等时，应补充状态或数据一致性观察点。
- 不稳定字段只能断言格式、存在性或范围，不断言固定值。

## 退回条件

以下情况必须退回修改：

- 任一用例缺少 `source_refs`。
- 任一接口字段没有来源且未标记待确认。
- 缺少接口契约时仍填充了无来源的 method、path、请求字段或响应字段。
- YAML 中出现真实敏感数据。
- 用例只断言请求成功，不断言业务结果。
- 草稿未包含 `review_questions`。
