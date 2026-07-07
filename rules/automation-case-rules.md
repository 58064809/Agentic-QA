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
- YAML 中出现真实敏感数据。
- 用例只断言请求成功，不断言业务结果。
- 草稿未包含 `review_questions`。
