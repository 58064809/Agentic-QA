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
5. 调用 `prompts/rag-automation-case-prompt.md` 生成 YAML 草稿。
6. 检查 YAML 顶层状态是否为 `needs_human_review`。
7. 检查每条用例是否包含 `source_refs`。
8. 检查是否存在真实敏感数据、完整域名或生产地址。
9. 写入 RAG 运行记录。
10. 输出草稿路径和 Review Gate 待确认项。

## 输出要求

- YAML 草稿默认 `status: needs_human_review`。
- 每条用例默认 `review_status: needs_human_review`。
- 每条用例必须包含来源引用。
- 无法确认的字段、错误码、权限、风控、幂等和数据状态必须写入待确认项。

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
