# Agents

`agents/` 不再为每个角色维护独立执行规范，避免与 Prompt、Workflow DSL 和 Runtime 节点形成第二事实源。

## 权威来源

| 内容 | 权威文件 |
|---|---|
| 仓库级 Agent 规则 | `AGENTS.md` |
| 可执行流程 | `workflows/runtime/*.workflow.yml` |
| 任务上下文清单 | `runtime/workflow/catalog.py` |
| 模型任务指令 | `prompts/` 中对应唯一 Prompt |
| 产物与审核路径 | `runtime/workspace.py`、`rules/artifact-path-rules.md` |
| 节点实现 | `runtime/graph/nodes/` |

## 当前角色

- Intent Router
- Workflow Orchestrator
- Requirement Analysis Agent
- Testcase Design Agent
- API Test Generation Agent
- UI Test Generation Agent
- API Discovery Agent
- Report Generation Agent
- Review Gate
- Artifact Promoter

角色职责摘要统一维护在根 `AGENTS.md`。新增角色时应先实现 Runtime 节点、Workflow DSL、唯一 Prompt 和测试，不再创建 `agents/<role>-agent.md`。
