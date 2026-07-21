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
每轮 ready 任务只派发 `max_concurrent_agents` 个，完成并由主管合并后才派发下一批；并发上限
是实际调度约束，不是仅记录在配置中的提示值。

默认硬预算为 24 次模型调用、50 次工具调用、3 次重规划、3 个并发 Agent 和 30 分钟。
超限时生成明确标记为 partial 的可审核候选，不伪造完成。`elapsed_seconds` 只累计 Agent
实际执行区间，不计人工审核等待时间；崩溃恢复和 Review Gate 恢复会继承已消耗时间，不能通过
重复 resume 重置 30 分钟上限。

`ModelPolicy` 是模型选择的单一入口。Flash 是常规结构化任务的默认档；Pro 用于复杂主管、
风险策略、长篇测试设计和失败分诊。思考模式只用于规划和高推理任务；测试设计使用 Pro
但关闭思考模式。单次模型请求默认 180 秒超时且禁用 SDK 隐式重试，后续显式重试由 Harness
预算约束。`reasoning_content` 不进入事件、checkpoint 或产物。一个 run 的模型、档位和
思考开关记录在 `model_routes`。模型 usage 按 run 记录增量，恢复执行时在原 run 上累加，
不得混入同一 Gateway 先前运行的累计值。Gateway 在每次结构化调用线程中暴露该次 usage，
Engine 再写入当前 run 的线程安全 accumulator；并行专家和并行 run 不通过共享总量做差。

`src/harness/knowledge/` 只存放无项目数据的通用 QA 方法。`SkillRegistry` 校验 reference
不可越出该目录、文件必须存在且非空，再合并进对应专家的系统指令。workspace source 与 MCP
结果仍是不可信运行输入，不能通过知识文件扩大工具权限或越过 Review Gate。

Playwright MCP 只从 `workspaces/<id>/workspace.yml` 的显式配置启用。stdio 模式固定使用官方
`@playwright/mcp@latest` 包，不提供任意命令执行入口；也可配置明确的 streamable HTTP URL。
每个新 run 都会 initialize、list tools，并将 allowlist 过滤后的名称和输入 Schema 冻结到
`tool-calls/mcp-playwright-snapshot.json`。同一 run 崩溃恢复时重新连接，但实时清单必须与冻结
快照完全一致，否则保持可恢复错误，不在权限或 Schema 漂移后继续执行。模型只看到本 run
实际配置且冻结后的 MCP 子工具与参数 Schema；未配置的 MCP provider 不进入模型工具目录。

状态变更采用双重显式授权：`workspace.yml` 的 `execution.environments` 先登记测试环境的
base URL 环境变量、HTTP 方法、UI mutation 和最大请求超时，`TaskRequest.execution_profile`
再请求其中的权限子集。未登记环境、越权方法/超时/UI mutation 以及 production-like 环境名称
都在创建 run 前拒绝；`analysis-only` 不允许 UI mutation。

专家返回 artifact 后，Engine 在候选写入前执行确定性契约检查。失败原因以
`artifact_validation_failed` 事件记录并反馈给同一专家，最多修复五次；只有通过检查的完整
内容才能写入 candidate。该局部修复仍计入模型调用预算，不扩大主管的重规划上限。

对于 source 中可识别的已确认逐场奖励配置表，Engine 会在质量门前确定性补充一个静态表驱动
核对用例及覆盖映射；字段值逐字来自 source，不由模型推算。对于 source 明确标记为建议或待确认的
比例、展示、内容判定和发放时机，以及低于门槛的样例，Engine 只会将模型断言收敛为条件式或阻塞式
用例，不补造产品行为。模型生成的单价或底标若与正式表冲突，会被移除并改写为仅依赖正式配置
快照和来源公式的核对用例，而不是尝试猜测正确金额。对抗类的三个来源条件必须在同一用例中
同时具备；单条件分类断言会被阻塞，并由来源驱动用例补齐三类证据核对。成长金只确定档位选择，
不会把待确认的发放时机改写成发放或前端金额结果。来源未定义的后台、日志、页面、按钮或账户
观察点会从候选中移除，相关步骤和结果只能保留为明确待确认的条件式内容。有效活动定义只证明
来源条件，不凭空生成模块、列表、标记或计数入口；成长金当前不限名额时，同档超额排序只能作为
不可执行的规则映射，不能修改正式配置制造场景。成长金说明文案不能以已发放或已到账为前置，
参与玩家去重也不能假设未确认的统计查询或前端观察点。内容缺少单项条件和对抗类负向场景只保留
来源条件证据，不生成内容数变化、前端分类标识或提示。低于最低核销门槛的比例与取整样例只能
作为不可执行数学说明；覆盖矩阵必须枚举实际用例 ID，不接受范围缩写，并与增强后的最终用例语义
保持一致。来源同时给出奖励
六条件或内容四条件时，覆盖矩阵必须逐项给出实际用例映射。覆盖矩阵中的“暂无、未覆盖、
待补充、后续设计”等占位映射会被质量门拒绝，不能以格式完整代替目标覆盖。增强过程记录为
`artifact_deterministically_enriched` 事件，增强后的完整候选仍必须通过同一质量门和人工
Review Gate。
