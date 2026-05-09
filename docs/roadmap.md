# Agentic-QA 路线图

## 001：保留并完善现有声明式工作台

继续维护 `AGENTS.md`、`COMMANDS.md`、`workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/`、`prd/`、`scripts/` 和 `tests/`。当前默认模式仍然是 Codex 驱动的标准化工作台。

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
