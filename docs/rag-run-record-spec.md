# RAG 运行记录规范

## 目标

RAG 运行记录用于保存一次“检索上下文并生成接口自动化 YAML 用例草稿”的全过程证据。它不是正式 QA 产物，但必须能解释生成内容来自哪里、哪些内容被模型使用、哪些缺口需要人工确认。

## 推荐路径

```text
rag/run_records/<run_id>.json
```

如果任务绑定具体 PRD 工作区，可在对应运行记录中引用：

```text
prd/<id>/runs/<run_id>/artifact-preview.md
prd/<id>/runs/<run_id>/api-test-cases.yml
prd/<id>/reviews/api-test-draft.review.yml
```

## 字段结构

| 字段 | 必填 | 说明 |
|---|---:|---|
| `schema_version` | 是 | 运行记录版本，第一版使用 `v1` |
| `run_id` | 是 | 本次 RAG 运行 ID |
| `created_at` | 是 | ISO 8601 时间 |
| `task_type` | 是 | 固定为 `rag_automation_case_generation` |
| `prd_path` | 否 | 关联 PRD 工作区 |
| `inputs` | 是 | PRD、Swagger、业务规则、历史经验等输入路径 |
| `corpus_snapshot` | 是 | 语料快照、索引版本和文档 hash |
| `retrieval_query` | 是 | 检索问题、目标接口、业务域和筛选条件 |
| `retrieved_chunks` | 是 | 被召回的 chunk 列表 |
| `selected_context` | 是 | 最终进入 Prompt 的上下文 |
| `generation` | 是 | Prompt、模型、输出路径和生成状态 |
| `output_artifacts` | 是 | 本次生成关联的 preview、YAML sidecar 和 Review Gate 路径 |
| `quality_checks` | 是 | source_refs、状态、安全和格式检查结果 |
| `review_gate` | 是 | 人审状态和待确认项 |
| `warnings` | 否 | 非阻塞风险和信息缺口 |

## retrieved_chunks

每个 chunk 至少包含：

| 字段 | 说明 |
|---|---|
| `chunk_id` | 稳定 chunk 标识 |
| `source_type` | `prd`、`api_document`、`swagger`、`openapi`、`apifox`、`business_rule`、`db_rule`、`automation_rule`、`historical_lesson` |
| `source_path` | 原始文件路径 |
| `locator` | 章节、接口路径、字段名或行号范围 |
| `score` | 检索分数或排序依据 |
| `summary` | 摘要，不保存敏感完整正文 |

## selected_context

最终进入 Prompt 的上下文必须保留映射关系：

- 每段上下文对应一个或多个 `chunk_id`。
- 每个接口字段、业务规则和断言建议都能反查来源。
- 被丢弃的高相关 chunk 应记录在 `warnings` 中说明原因，例如上下文预算不足或来源未确认。

## 质量检查

第一版至少检查：

- YAML 顶层 `status` 是否为 `needs_human_review`。
- 每条用例是否包含非空 `source_refs`。
- 是否出现真实 token、Cookie、手机号、身份证、银行卡或生产域名。
- 是否只使用相对接口路径。
- 是否包含待人工确认项。
- 缺少 Swagger / OpenAPI / Apifox 接口契约时，是否避免编造 method、path、请求字段和响应字段，并把契约缺口写入 `review_questions`。

## 输出产物路径

RAG 自动化用例生成必须复用现有候选产物、Review Gate 和 promote 体系：

| 字段 | 路径 | 说明 |
|---|---|---|
| `output_artifacts.preview` | `prd/<id>/runs/<run_id>/artifact-preview.md` | 人类可读候选预览 |
| `output_artifacts.yaml_cases` | `prd/<id>/runs/<run_id>/api-test-cases.yml` | 机器可消费 YAML sidecar 草稿 |
| `output_artifacts.review` | `prd/<id>/reviews/api-test-draft.review.yml` | Review Gate 记录 |

正式 YAML 只允许在 Review Gate 通过并执行 promote 后写入 `prd/<id>/artifacts/api-test-cases.yml`。

## 模板

运行记录模板见 `knowledge/templates/rag-run-record-template.json`。
