# 10 RAG 接口自动化用例生成工作流

## 目标

基于 PRD、Swagger / OpenAPI、业务规则和公司知识库，通过 RAG 构建上下文，生成可人工审核的 YAML 接口自动化用例草稿。

本工作流是第一版工程骨架，不引入复杂 Runtime，不新增 Agent 调度器。

## 触发语义

适用用户意图示例：

- 基于 PRD 和 Swagger 生成接口自动化 YAML 用例草稿。
- 用公司业务知识库补充接口自动化用例。
- 基于 RAG 生成可给 pytest 执行的接口用例草稿。

## 输入

| 输入 | 路径或来源 | 必填 |
|---|---|---:|
| PRD | `prd/<id>/input/requirement.md` | 是 |
| Swagger / OpenAPI / Apifox | `prd/<id>/input/` 或 `knowledge/api/` | 否 |
| 业务规则 | `knowledge/business/` | 否 |
| 数据库规则 | `knowledge/db/` | 否 |
| 自动化规则 | `knowledge/automation/` | 是 |
| 历史经验 | `knowledge/historical/` | 否 |

## 步骤

1. 识别 PRD 工作区和生成目标。
2. 加载 PRD、接口契约、业务规则、自动化规范和历史经验。
3. 按接口、字段、业务规则、断言策略和历史风险切分上下文。
4. 检索与目标接口和业务规则相关的 chunk。
5. 构建 Prompt 上下文，并保留 `source_refs` 映射。
6. 使用 `prompts/rag-automation-case-prompt.md` 生成 YAML 草稿。
7. 按 `rules/automation-case-rules.md` 和 `rules/source-reference-rules.md` 做质量检查。
8. 写入 RAG 运行记录。
9. 将 YAML 草稿标记为 `needs_human_review`，等待 Review Gate。

## 输出

| 输出 | 说明 |
|---|---|
| `prd/<id>/runs/<run_id>/api-test-cases.yml` | YAML 接口自动化用例草稿 |
| `rag/run_records/<run_id>.json` | RAG 运行记录 |
| Review Gate 待确认项 | 需要人工确认的接口契约、业务规则、数据和执行风险 |

## 质量门

- YAML 顶层必须是 `status: needs_human_review`。
- 每条用例必须包含非空 `source_refs`。
- 未确认字段必须进入 `review_questions`。
- 不得出现真实敏感数据或生产地址。
- 不得直接执行接口请求。

## 下游

人工审核通过后，才允许将 YAML 交给现有 pytest 框架执行。执行仍需满足环境、账号、数据和风险确认规则。
