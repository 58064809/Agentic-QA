# Harness v2 架构

Agentic-QA 是单 Python distribution 的整洁模块化单体，依赖只能由外向内：

```text
interfaces -> application -> domain
     |              ^
     v              |
bootstrap -> infrastructure
```

| 层 | 职责 |
|---|---|
| `domain/` | 领域模型、Review Gate 规则、Artifact 规则和质量策略协议 |
| `application/` | 创建、启动、查询、恢复、审核用例，以及 Repository、Workflow、Model、Tool、Checkpoint 端口 |
| `infrastructure/` | 文件仓储、PostgreSQL、LangGraph、模型、MCP、RAG、HTTP/API 与 manifest 适配器 |
| `interfaces/` | `Harness` v2 门面和薄 CLI |
| `bootstrap.py` | 唯一组合根，实例化端口、策略和适配器 |

AST 架构测试禁止 `domain` 和 `application` 导入 LangGraph、psycopg、OpenAI、MCP、
`infrastructure`、`interfaces` 或组合根；`domain` 也不得依赖 `application`。LangGraph 只存在于
workflow adapter，公开模型不泄露其状态类型。

文件持久化分为 Workspace Repository、Run/Event Repository、Artifact/Review Repository。
`FilesystemStore` 只是基础设施组合对象。`state.json` 是公开投影，PostgreSQL checkpoint 才是
恢复执行的事实来源；生产运行没有 SQLite 或内存 fallback。thread ID 由
`workspace_id + run_id` 组成，恢复必须使用同一个 thread。

主管通过 LangGraph `Send` 派发无依赖任务，专家仅追加任务结果，主管单点合并。每批最多运行
`max_concurrent_agents` 个专家。计划、工具、模型和修订均受预算约束；超限只生成明确标记为
partial 的审核材料，不伪造完成。

Tool Runtime 负责授权、预算、参数 Schema、幂等记录和 Handler 注册。内置工具与 MCP Handler
通过注册表选择，不使用中央条件分发。Playwright MCP 清单按 run 冻结，恢复时若实时清单与
冻结快照不同则保持可恢复错误。

质量策略注册表始终执行通用产物契约，并按 `workspace.yml.quality_policies` 追加命名策略。
通用策略校验固定 11 列、覆盖矩阵、证据真实性和 Schema；`city-opening-rewards` 独立承载
城市开局奖励业务规则。每次校验、修订或拒绝都记录策略名、版本、原因和动作。
