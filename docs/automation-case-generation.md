# 接口自动化 YAML 用例生成

## 目标

将 PRD、Swagger / OpenAPI、业务规则和 RAG 检索上下文转化为可人工审核的 YAML 接口自动化用例草稿。草稿通过 Review Gate 后，才允许交给现有 pytest 框架执行。

## 输入

| 输入 | 说明 |
|---|---|
| PRD | 业务目标、流程、规则、权限和待确认项 |
| Swagger / OpenAPI / Apifox | 接口路径、方法、字段、响应结构、错误码和鉴权 |
| 服务级 OpenAPI 契约库 | Apifox 导出的服务级 OpenAPI JSON，默认路径为 `knowledge/api/<service>/openapi.json` |
| PRD 接口范围 | `prd/<id>/input/api-scope.md`，用于声明服务名和本次需求涉及的接口范围 |
| 业务规则 | 条件、动作、结果、状态流转和风控规则 |
| 数据库知识 | 状态字段、唯一约束、枚举和数据一致性观察点 |
| 自动化规范 | YAML schema、断言规则、变量提取和安全约束 |
| 历史经验 | 历史缺陷、漏测点、误报原因和回归风险 |

## 输出

RAG 自动化 YAML 草稿不绕过现有产物流转。一次生成默认产生以下候选与审核记录：

```text
prd/<id>/runs/<run_id>/artifact-preview.md      # 人类可读预览
prd/<id>/runs/<run_id>/api-test-cases.yml       # 机器可消费 YAML 草稿
prd/<id>/reviews/api-test-draft.review.yml      # Review Gate 记录
prd/<id>/artifacts/api-test-cases.yml           # 审核通过并 promote 后的正式 YAML
```

`api-test-cases.yml` 是 `api_test_draft` 同一 Review Gate 下的 sidecar 候选产物。未审核前只能位于 `runs/<run_id>/`，不得直接写入 `artifacts/` 或作为正式可执行资产。

输出必须满足：

- `schema_version: agentic-qa.api-cases.v1.1`。
- `artifact_type: api_automation_cases`。
- 顶层 `status: needs_human_review`。
- 顶层 `human_review_required: true`。
- 每条用例必须包含 `source_refs`。
- 接口路径只能写相对路径，不能写完整域名。
- 账号、密码、token、Cookie、动态 ID 只能使用变量或环境占位。
- 必须包含 `review_questions`，列出待人工确认项。
- 缺少 Swagger / OpenAPI / Apifox 接口契约时，不得编造 `request.method`、`request.path`、请求字段、响应字段或错误码；只能生成待确认草稿，并把接口契约缺口写入 `review_questions`。
- 普通接口文档仅能确认部分契约时使用 `contract_status: partial`；禁止生成无来源的默认 200/201、400/422、401/403 或 `code/data/message` 字段断言。

## 服务级 OpenAPI 召回

Apifox 导出的服务级 OpenAPI JSON 应按服务沉淀到：

```text
knowledge/api/<service>/openapi.json
```

例如 product 服务：

```text
knowledge/api/product/openapi.json
```

RAG 生成接口自动化 YAML 时不得把完整服务级 OpenAPI 塞进 Prompt。必须先解析 `paths`，按 operation 建立 chunk，再结合 `prd/<id>/input/api-scope.md` 精准召回。

`api-scope.md` 推荐格式：

```yaml
service: product
paths:
  - GET /product/shop/store/getCommodityDetail
  - POST /product/mobile/shop/store/searchCommodities
keywords: 商品 搜索 详情
```

召回规则：

- 声明 `service: product` 时，只读取 `knowledge/api/product/openapi.json`。
- 明确列出 `method path` 时，只召回这些接口。
- 只列出 path 时，可召回该 path 下全部 method。
- 未列出具体 path 时，允许基于 PRD 关键词、接口 summary、path、tags 做检索，但 `confidence` 不得高于 `medium`。
- `api-scope.md` 指定的 path/method 未命中 OpenAPI 时，不得回退编造 method/path/request/response 字段事实，必须生成 `contract_status: missing` 草稿并写入 `review_questions`。

每个 OpenAPI operation chunk 的 `chunk_id` 格式：

```text
openapi.<service>.<METHOD>.<path_hash>
```

命中 OpenAPI 契约时，YAML 来源必须满足：

```yaml
source_type: openapi
source_path: knowledge/api/product/openapi.json
contract_status: confirmed
confidence: high
```

## 用例最小字段

每条用例至少包含：

| 字段 | 说明 |
|---|---|
| `id` | 用例 ID |
| `title` | 用例标题 |
| `priority` | `P0`、`P1`、`P2`、`P3` |
| `source_refs` | 来源引用，不能为空 |
| `request` | method、path、headers、query、body；缺少接口契约时不得编造 |
| `assertions` | HTTP、业务码、字段、状态或数据库观察点 |
| `variables` | 前置变量、提取变量或环境变量 |
| `review_status` | 默认 `needs_human_review` |

完整格式见 `knowledge/automation/yaml-case-schema.md`。


## Runtime workflow 结构

RAG 自动化 YAML 生成使用 LangGraph subgraphs 拆分阶段，避免父 workflow 继续膨胀：

- `rag_automation_context_pipeline`：命令路由、workflow 选择、需求规范化、上下文加载和 OpenAPI 范围召回。
- `rag_automation_case_generation_core`：YAML 草稿生成、质量校验和按 Review Gate 意见修订。
- `rag_automation_promote_pipeline`：审核通过后的正式产物发布和 metadata 更新。

父图 `rag_automation_case_generation` 只保留阶段编排、`artifact_preview_writer` 和 `review_gate`，Review Gate 继续通过 LangGraph interrupt 暂停并等待人工输入。复杂 graph 的 trace、debug、状态转移可视化和 runtime metrics 使用 LangSmith，本地运行记录不再保存节点事件流。

## Review Gate

AI 生成的 YAML 只表示候选草稿，不得绕过人工确认。人工至少需要确认：

- 接口路径、方法、字段、错误码是否与 Swagger / Apifox 一致。
- 业务规则、权限、风控和幂等预期是否正确。
- 测试账号、测试数据、环境和风险是否允许执行。
- 断言是否会误伤不稳定字段，例如时间戳、随机 ID、异步状态。

## 与 pytest 执行框架的边界

现有 pytest 执行框架只消费已确认或明确授权的 YAML 文件。没有显式环境变量和执行授权时，测试应跳过，不应请求真实服务。

推荐执行前置条件：

- `AGENTIC_QA_API_CASES_FILE` 指向经人工确认的 YAML 文件。
- `AGENTIC_QA_BASE_URL` 指向授权测试环境。
- 账号、token、租户、动态数据通过环境变量或 fixture 注入。
