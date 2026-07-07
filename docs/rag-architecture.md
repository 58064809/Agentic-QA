# RAG 自动化用例生成架构

## 目标

本架构用于建设“公司业务知识库 + RAG 检索 + 接口自动化用例生成”的第一版 MVP 骨架。目标是让 AI 在生成 YAML 接口自动化用例草稿时，能同时参考 PRD、Swagger / OpenAPI、业务规则、数据库约束、自动化规范和历史经验，并保留可追溯来源。

本文件只描述工程骨架和协作契约，不引入复杂 Runtime，不自研 Agent 调度器。

## 范围

第一版只覆盖以下能力：

- 按知识类型沉淀公司业务知识、接口契约、数据库约束、自动化规范和历史经验。
- 对输入文档进行加载、切分、索引和检索。
- 构建生成接口自动化 YAML 用例草稿所需上下文。
- 记录 RAG 检索与生成过程，便于人工审核和问题追溯。
- 输出 `status: needs_human_review` 的候选用例，不直接进入正式资产。

第一版不覆盖：

- 不替代人工评审和 Review Gate。
- 不自动执行真实接口请求。
- 不接生产环境。
- 不生成最终缺陷结论或 QA 结论。
- 不新增独立 Agent 调度器。

## 目录分层

知识库目录：

| 目录 | 用途 |
|---|---|
| `knowledge/business/` | 公司业务规则、领域对象、状态流转和权限规则 |
| `knowledge/api/` | Swagger、OpenAPI、Apifox 导出摘要和接口契约说明 |
| `knowledge/db/` | 数据库表、字段、约束、状态枚举和数据一致性规则 |
| `knowledge/automation/` | YAML 用例结构、断言规则、变量提取和执行约束 |
| `knowledge/historical/` | 历史缺陷、漏测复盘、误报原因和高风险经验 |
| `knowledge/templates/` | RAG 运行记录、产物和审核模板 |

RAG 工程目录：

| 目录 | 用途 |
|---|---|
| `rag/loaders/` | 加载 PRD、Swagger、Markdown、YAML、JSON 等文档 |
| `rag/chunkers/` | 按章节、接口、字段、业务规则切分文档 |
| `rag/index/` | 保存索引元信息、版本、语料快照和构建记录 |
| `rag/retrievers/` | 按任务检索业务规则、接口字段、断言规则和历史经验 |
| `rag/context_builder/` | 组装 Prompt 上下文，控制来源、预算和缺口 |
| `rag/run_records/` | 保存每次 RAG 检索与生成的追踪记录 |

## 主链路

```text
PRD / Swagger / 业务规则
  ↓
文档加载与规范化
  ↓
按业务规则、接口、字段、断言点切分
  ↓
索引与语料快照记录
  ↓
按接口自动化用例生成任务检索
  ↓
构建带 source_refs 的上下文
  ↓
AI 生成 YAML 接口用例草稿
  ↓
写入 runs/<run_id>/artifact-preview.md
  ↓
写入 runs/<run_id>/api-test-cases.yml
  ↓
质量检查
  ↓
Review Gate（reviews/api-test-draft.review.yml）
  ↓
promote 后写入 artifacts/api-test-cases.yml
  ↓
人工确认后交给现有 pytest 框架执行
```

## 上下文构建原则

- PRD 和已确认业务规则用于定义业务预期。
- Swagger / OpenAPI 用于定义接口路径、方法、请求字段、响应字段、错误码和鉴权方式。
- 缺少 Swagger / OpenAPI / Apifox 接口契约时，不得编造接口路径、方法、请求字段、响应字段、错误码或鉴权方式；只能生成待确认草稿并写入 `review_questions`。
- 数据库知识只作为数据一致性和状态校验依据，不反推未确认接口字段。
- 自动化知识用于约束 YAML 格式、断言层级、变量提取和安全边界。
- 历史经验用于补充风险场景和漏测提醒，不得替代当前需求事实。

## 来源追踪

RAG 返回给生成模型的每条上下文必须保留来源信息。生成的每条 YAML 用例也必须包含 `source_refs`，至少能追溯到 PRD、接口契约、业务规则或历史经验中的一项。

如果某条用例只能基于推断生成，必须：

- 将该用例标记为待确认。
- 在 `source_refs` 中标注推断依据。
- 在 `review_questions` 中写明需要人工确认的问题。

## 输出边界

AI 生成的 YAML 接口用例默认是候选草稿：

```yaml
status: needs_human_review
human_review_required: true
```

草稿可进入 Review Gate，不得直接作为正式自动化资产执行。只有人工确认执行环境、账号、数据、风险和用例内容后，才允许交给现有 pytest 执行入口。

产物流转固定为：

```text
runs/<run_id>/artifact-preview.md
runs/<run_id>/api-test-cases.yml
reviews/api-test-draft.review.yml
artifacts/api-test-cases.yml
```

其中 `artifacts/api-test-cases.yml` 只能由审核通过后的 promote 写入。
