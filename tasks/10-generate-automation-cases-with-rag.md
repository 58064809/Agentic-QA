# 任务 SOP：基于 RAG 生成接口自动化 YAML 用例

## 目标

将 PRD、Swagger / OpenAPI、业务规则和公司知识库转化为可人工审核的 YAML 接口自动化用例草稿。

## 前置条件

- 已有 PRD 工作区。
- PRD 原文已放入 `prd/<id>/input/requirement.md`。
- 如有接口文档，应放入 `prd/<id>/input/` 或 `knowledge/api/`。
- 自动化 YAML 规则已放入 `knowledge/automation/`。
- 用户明确要求生成草稿，而不是直接执行。

## 操作步骤

1. 确认目标 PRD 工作区。
2. 读取 PRD、接口文档、业务规则、数据库规则、自动化规则和历史经验。
3. 使用 RAG 检索接口路径、字段、业务规则、断言策略和历史风险。
4. 构建带来源映射的上下文。
5. 调用 `prompts/rag-automation-case-prompt.md` 生成人类可读预览和 YAML sidecar 草稿。
6. 检查 YAML 顶层状态是否为 `needs_human_review`。
7. 检查每条用例是否包含 `source_refs`。
8. 检查是否存在真实敏感数据、完整域名或生产地址。
9. 写入 RAG 运行记录，并在记录中登记 preview、yaml_cases、review 路径。
10. 输出候选预览、YAML sidecar 和 Review Gate 待确认项。


## Runtime graph 拆分

为避免 `rag_automation_case_generation` 父 workflow 持续膨胀，当前 Runtime 使用 LangGraph subgraphs：

```text
rag_automation_case_generation
  -> context_pipeline: rag_automation_context_pipeline
  -> case_generation: rag_automation_case_generation_core
  -> artifact_preview_writer
  -> review_gate
  -> promote_pipeline: rag_automation_promote_pipeline
```

扩展规则：

- 上下文加载、PRD 规范化、OpenAPI 范围召回相关节点放入 `rag_automation_context_pipeline`。
- YAML 生成、质量校验、修订相关节点放入 `rag_automation_case_generation_core`。
- 审核通过后的正式发布和 metadata 更新放入 `rag_automation_promote_pipeline`。
- `review_gate` 保留在父图，确保 LangGraph interrupt 暂停点清晰可恢复。
- 不要把新增阶段直接堆进父 workflow；父图只负责阶段编排和跨阶段条件路由。
- subgraph 的 trace、debug、状态转移可视化和 runtime metrics 使用 LangSmith；本地运行记录只保存恢复、审核和产物审计所需信息。

## 输出要求

- YAML 草稿默认 `status: needs_human_review`。
- 每条用例默认 `review_status: needs_human_review`。
- 每条用例必须包含来源引用。
- 无法确认的字段、错误码、权限、风控、幂等和数据状态必须写入待确认项。
- 输出路径必须遵循现有产物流转：`runs/<run_id>/artifact-preview.md` 为主候选预览，`runs/<run_id>/api-test-cases.yml` 为机器可消费 sidecar，`reviews/api-test-draft.review.yml` 为 Review Gate，审核通过后才允许 promote 到 `artifacts/api-test-cases.yml`。

## 人工确认点

- Swagger / Apifox 字段是否完整。
- 必填、枚举、错误码、鉴权和权限是否准确。
- 幂等、风控、频控、并发和状态流转是否符合业务规则。
- 测试账号、环境、数据和执行风险是否已授权。

## 禁止事项

- 不直接执行接口请求。
- 不把草稿当正式自动化资产。
- 不写真实账号、密码、token、Cookie 或生产域名。
- 不在信息不足时编造接口契约。
- 缺少 Swagger / OpenAPI / Apifox 接口契约时，不得编造 `request.method`、`request.path`、请求字段和响应字段；只能生成待确认草稿并写入 `review_questions`。
