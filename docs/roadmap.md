# Agentic-QA 路线图

## 001：保留并完善现有声明式工作台

继续维护 `AGENTS.md`、`COMMANDS.md`、`workflows/`、`agents/`、`prompts/`、`rules/`、`qa-methods/`、`knowledge/`、`prd/`、`scripts/` 和 `tests/`。当前默认模式为 Runtime 驱动的自然语言执行引擎。

## 002：新增 Runtime 最小骨架

在后续任务中新增轻量 `runtime/` 骨架。该骨架只做最小可运行闭环，不引入复杂平台、不接生产环境、不替代声明式资产。

## 003：做第一个 LangGraph 流程：测试用例生成

第一条 Runtime 闭环聚焦 `workflows/02-testcase-generation-workflow.md`，读取现有 Prompt、Rules、Skills、Knowledge，生成 `prd/<需求名>/20-testcases/testcases.md` 草稿。

## 004：加入 Human-in-the-loop

对写入、执行、失败定性、报告结论和归档动作加入人工审核门。Runtime 必须暂停等待确认，不得直接替代人工判断。

## 005：加入持久化和运行记录

加入 Checkpoint、运行记录、状态恢复和可观测性。优先保持轻量，不在早期引入复杂数据库或平台服务。

## 006：接入真实 QA 工具

逐步接入 pytest、Playwright、Allure、日志分析和报告生成工具。真实业务环境执行必须由人工授权，且不得默认连接生产环境。

## 007：纯自然语言 CLI 入口

新增 Phase 1.5 自然语言交互入口，定位为 Codex-first 主线的 CLI 对等体。用户无需记忆子命令、参数或工作流名称，直接以纯自然语言描述任务意图即可驱动完整 QA 流程。

### 能力边界

- **纯自然语言入口**：全局命令 `agentic-qa`，只接受自然语言文本，无 `--flag`、无子命令、无位置参数。示例：`agentic-qa 帮我分析 prd/支付模块的需求`。
- **LLM 语义路由**：入口不硬编码意图分类逻辑，由 LLM 将用户输入路由到对应 Workflow（需求分析 / 测试用例生成 / 增量修订 / 导出评审文件 / 状态标记等），同时携带目标 PRD 上下文。
- **Session 持久化**：每次交互关联一个 session ID，自动写入 `.runtime/sessions/`，记录对话轮次、路由决策、已写入产物路径和人工确认状态。同一 session 内连续对话自动延续上下文，不打断工作流。
- **自动写入（不打断）**：LLM 确认意图后直接按 Workflow 规则写入产物草稿，不再额外等待用户二次确认是否写入；人工审核门保留在写入之后（评审环节），不前置为执行阻断。
- **无子命令无参数**：入口不提供 `--help`、`--dry-run`、`--confirm`、`--use-llm` 等参数开关。dry-run / confirm 等策略由 Runtime 内部根据 session 状态和 Workflow 规则自动决定。

### 与现有 Runtime 的关系

- 纯自然语言入口与 Codex-first 声明式工作台共存，各自面向不同使用场景。
- 复用现有 Runtime 的 Writer、Checkpointer、Metadata 更新等基础设施。
- 不影响现有 Codex-first 主线：用户仍可在 PyCharm Chat 中直接与 Codex 对话，两种入口并行。

### 后续演进方向

- 支持多轮对话纠错：用户可在同一 session 内补充信息或修正需求，LLM 增量更新已有产物。
- Session 恢复：中断后可通过 session ID 恢复上次对话上下文。
- 可选静默模式：仅输出关键摘要，不输出完整工作流日志。
