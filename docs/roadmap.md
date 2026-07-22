# 路线图

## 当前已实现

- v2 命令门面与 CLI，所有 run 操作使用 `workspace_id + run_id`。
- domain/application/infrastructure/interfaces/bootstrap 分层和 AST 依赖测试。
- LangGraph 动态派发、PostgreSQL checkpoint、interrupt、崩溃恢复、预算和 partial 降级。
- Workspace、Run/Event、Artifact/Review 文件 Repository 与确定性 promote。
- 通用质量策略和显式选择的 `city-opening-rewards` 策略。
- Agent/Skill/Tool manifest、DeepSeek/OpenAI-compatible 模型路由、Playwright MCP 快照。
- 本地词法与 OpenAI-compatible embedding RAG Provider。
- API cases v1.1、execution evidence v1、failure triage v1。

## 后续

- 可选 Playwright MCP live smoke CI 和更多录制场景。
- 更多只读测试管理系统连接器。
- 外部缺陷系统写入仍不在当前范围；证据不足的失败保持 unconfirmed。
