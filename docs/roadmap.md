# 路线图

本页区分已实现能力、后续方向和当前产品边界；“计划中”不代表运行时已经提供对应接口。

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
| OpenAPI 3.x/Swagger 2.0 归一化与强类型 API Candidate | 已实现 | `domain/schemas/openapi.py`、`infrastructure/tools/openapi.py` |
| 冻结 HAR/JSON 的离线 API Discovery 与脱敏报告 | 已实现 | `domain/schemas/api_discovery.py`、`infrastructure/tools/network_capture.py` |
| 显式测试环境中的 Playwright MCP 实时接口发现 | 已实现 | `tools/playwright_network.py`、`network.capture.live` |
| Playwright MCP live smoke CI | 已实现 | 本地临时站点、官方 MCP 进程、真实浏览器网络捕获与脱敏断言 |
| API Discovery 脱敏目录导出 | 已实现 | Candidate manifest 哈希绑定；Review 后确定性发布 `current.catalog.json` |
| API cases、execution evidence、failure triage Schema | 已实现 | `src/harness/domain/schemas/` |
| TestRail 只读测试资产连接器 | 已实现 | 固定查询 allowlist、环境变量凭据、分页与响应预算、run 工具记录 |

## 计划中

| 能力 | 状态 | 验收边界 |
|---|---|---|
| 更多只读测试管理系统连接器 | 计划中 | 在 TestRail 之外继续扩展，且不扩大 Review/Execution 权限 |

## 明确不在当前范围

| 能力 | 原因 |
|---|---|
| 自动批准或绕过 Review Gate | 破坏人工发布边界 |
| 原始 HAR 进入 Candidate 或 published | Header、Cookie、query 和 body 可能包含凭据或个人数据；脱敏目录承担可携带导出 |
| 生产环境 API/UI mutation | ExecutionProfile 会拒绝 production-like 环境 |
| 外部缺陷系统自动写入 | 当前只生成 unconfirmed 候选，不连接外部写入端口 |
| v1 workspace 自动迁移 | 旧数据只保留，不读取、不改写 |
| SQLite 或生产内存 checkpoint | PostgreSQL 是唯一生产 checkpoint |
