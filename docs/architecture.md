# Harness 架构

Agentic-QA 采用测试主管与专家 Agent 分层。公开协议不依赖 LangGraph，内部后端可替换。

| 层 | 职责 |
|---|---|
| Python API / CLI | 接收 `TaskRequest`，提供 run、stream、resume、inspect |
| QA Supervisor | 规划、选择专家、验收结果、受预算约束地重规划 |
| Expert Agents | 在 manifest 的 Skill 和 Tool allowlist 内完成单一 QA 专业任务 |
| Skill Knowledge | 随 wheel 发布、由 Skill manifest 显式引用的通用 QA 方法 |
| ModelGateway | 单一 DeepSeek provider、Flash/Pro 集中路由、结构化输出、usage 与错误归一化 |
| Tool / MCP | typed tool、run 级冻结快照、风险与执行 profile 校验 |
| Artifact Store | run 投影、candidate、review、published 历史 |
| LangGraph Checkpointer | SQLite 执行事实、并行写入和 interrupt 恢复 |
| Review Gate | 只接受人工 `ReviewDecision`，批准后确定性 promote |

`src/harness/backend.py` 定义 reducer-safe `HarnessState` 和真实 `StateGraph`。主管通过
`Send` 派发无依赖任务，专家只追加任务级结果，再由主管单点合并。Review Gate 使用
`interrupt()`；`resume` 以同一 run_id/thread_id 恢复。公开 `RunSnapshot` 不含 LangGraph 类型。

默认硬预算为 24 次模型调用、50 次工具调用、3 次重规划、3 个并发 Agent 和 30 分钟。
超限时生成明确标记为 partial 的可审核候选，不伪造完成。

`ModelPolicy` 是模型选择的单一入口。Flash 是常规结构化任务的默认档；Pro 只用于复杂主管
规划、风险策略和失败分诊。思考模式只用于规划和高推理任务，且 `reasoning_content` 不进入
事件、checkpoint 或产物。一个 run 的模型、档位和思考开关记录在 `model_routes`。

`src/harness/knowledge/` 只存放无项目数据的通用 QA 方法。`SkillRegistry` 校验 reference
不可越出该目录、文件必须存在且非空，再合并进对应专家的系统指令。workspace source 与 MCP
结果仍是不可信运行输入，不能通过知识文件扩大工具权限或越过 Review Gate。
