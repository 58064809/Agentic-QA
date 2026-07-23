# Agentic-QA 文档

Agentic-QA 生成不可覆盖的候选产物，并以人工 Review Gate 隔离 Agent 输出与正式发布。

## 按读者选择入口

| 读者 | 首选文档 | 解决的问题 |
|---|---|---|
| CLI 使用者 | [从零开始](getting-started.md) | 如何完成配置、执行、审核和发布 |
| CLI 使用者 | [CLI 参考](cli-reference.md) | 每条命令、参数和退出码是什么 |
| 环境维护者 | [配置参考](configuration.md) | 环境变量、workspace、RAG 和 PostgreSQL 如何配置 |
| Python 集成者 | [Harness 契约](harness-contracts.md) | 七个公开方法与强类型输入输出 |
| 审核人 | [Review Gate](review-gate.md) | 哪些版本能批准，发布如何防绕过 |
| 维护者 | [架构](architecture.md) | 分层依赖、组合根和运行链路 |
| 维护者 | [工作区与产物版本](artifact-versioning.md) | 文件职责、原子提交和恢复边界 |
| 测试设计者 | [测试用例标准](testcase-standards.md) | 固定 11 列与证据要求 |
| API 测试者 | [API 测试契约](api-test-generation.md) | 来源可信度和机器 Schema |

## 事实来源

| 内容 | 事实来源 |
|---|---|
| 公开 API | `src/harness/interfaces/facade.py`、`src/harness/contracts.py` |
| CLI | `src/harness/interfaces/cli.py` |
| Agent、Skill、Tool | `src/harness/manifests/` |
| Agent 运行知识 | `src/harness/knowledge/` |
| 运行行为 | `src/harness/domain/`、`application/`、`infrastructure/` |
| 本站文档 | 对事实来源的使用说明，不替代实现契约 |

## 机器可读 Schema

| Artifact | Schema |
|---|---|
| API cases v1.1 | [JSON Schema](schemas/api-cases.v1.1.schema.json) |
| Execution evidence v1 | [JSON Schema](schemas/execution-evidence.v1.schema.json) |
| Failure triage v1 | [JSON Schema](schemas/failure-triage.v1.schema.json) |
