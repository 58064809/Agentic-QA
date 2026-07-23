# 路线图

## 已实现

| 能力 | 状态 | 实现证据 |
|---|---|---|
| v2 Facade 与 CLI | 已实现 | `src/harness/interfaces/` |
| 分层与 AST 依赖测试 | 已实现 | `src/harness/domain/`、`application/`、架构测试 |
| LangGraph + PostgreSQL checkpoint | 已实现 | `src/harness/infrastructure/workflow/`、`persistence/` |
| Source 冻结、Candidate 原子提交、Review/Publication Journal | 已实现 | persistence adapters |
| 通用质量与显式业务 pack | 已实现 | `src/harness/infrastructure/quality/` |
| Agent/Skill/Tool manifests 与内置知识 | 已实现 | `src/harness/manifests/`、`knowledge/` |
| 跨 AI AgentRequest 与本地 MCP stdio | 已实现 | `application/agent_request/`、`interfaces/mcp_server.py` |
| 本地/远程 RAG、Playwright MCP、只读 PostgreSQL Tool | 已实现 | infrastructure adapters |
| API cases、execution evidence、failure triage Schema | 已实现 | `src/harness/domain/schemas/` |

## 计划中

| 能力 | 状态 | 验收边界 |
|---|---|---|
| Playwright MCP live smoke CI | 计划中 | 只针对明确测试环境和 allowlist |
| 更多只读测试管理系统连接器 | 计划中 | 不扩大 Review/Execution 权限 |

## 明确不在当前范围

| 能力 | 原因 |
|---|---|
| 自动批准或绕过 Review Gate | 破坏人工发布边界 |
| 生产环境 API/UI mutation | ExecutionProfile 明确禁止 |
| 外部缺陷系统自动写入 | 证据和根因不足时必须保持 unconfirmed |
| v1 workspace 自动迁移 | 旧数据只保留，不读取、不改写 |
| SQLite 或生产内存 checkpoint | PostgreSQL 是唯一生产 checkpoint |
