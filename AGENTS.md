# 自动化代理协作规范

本仓库中的 Agent 是文件化角色定义，供各类自动化代理、AI 编程助手、Runtime 执行器和集成方参考使用。

## 通用职责

- Runtime 默认通过 LLM 语义路由识别用户意图，自动调用对应 Agent 角色和 Workflow；LLM 不可用时降级到确定性路由和评审级草稿。
- 自动化代理、AI 编程助手或集成执行器处理本仓库任务时，必须先读取本文件，再读取具体 Agent、规则、Workflow 或模块文档。
- `README.md` 面向人工用户，只承载产品介绍、快速开始、常用命令和当前能力说明；代理执行契约、路径约束、运行事实和协作规则应维护在本文件或 `rules/`、`workflows/`、`prompts/`、`skills/`、`knowledge/` 中。
- 严格遵守 `rules/` 中的路径、命名、状态和审核门规则。
- 完成任务后的 Chat 回复必须遵守 `rules/agent-output-rules.md`，只给摘要、关键路径、验收结果和待人工确认项。
- 完成任务后必须按 `rules/agent-output-rules.md` 的标准完成回执模板回复。
- 只在目标 PRD 工作区内写入对应产物。
- 对不确定内容使用"待确认""待补充""假设"标记，不伪造结论。

## 文档边界

- 面向人的产品说明、安装使用、常用命令和路线图写入 `README.md`。
- 面向自动化代理、AI 编程助手和集成执行器的执行规范、协作边界、当前实现事实、路径规则和禁止事项写入 `AGENTS.md` 或 `rules/`。
- 详细配置字段说明写入 `configs/README.md`。
- RAG 模块设计、索引、召回和降级说明写入 `rag/README.md`。
- 生产级 Runtime 演进方案写入 `docs/production-agent-runtime-roadmap.md`。
- 不得把长篇工作流契约、内部状态 Schema、代理执行提示或仅供机器解析的内容放回根 `README.md`。

## 协作边界

| Agent | 职责 | 输出 |
|-------|------|------|
| Requirement Analysis Agent | 需求拆解和风险识别 | `runs/<run_id>/analysis/requirement-analysis.md` |
| Testcase Design Agent | 测试设计和覆盖矩阵 | `runs/<run_id>/cases/test-cases.md` |
| API Test Generation Agent | API 自动化脚本草稿 | `automation/api/generated/` |
| UI Test Generation Agent | UI 自动化脚本草稿 | `automation/ui/generated/` |
| Test Execution Agent | 执行命令并收集结果 | `execution/runs/` |
| Failure Analysis Agent | 失败分类和证据整理 | `defects/failure-analysis.md` |
| Bug Draft Agent | 缺陷草稿 | `defects/bug-drafts/` |
| Report Generation Agent | QA 报告草稿 | `report/qa-review.md` |
| Archive Agent | 归档前校验和索引生成 | `archive/index.md` |

## Runtime Agent

Runtime Agent 是执行引擎核心角色，负责自然语言入口、LLM 语义路由、会话管理和自动写入。

### LLM 语义路由 Agent

- 唯一入口为自然语言指令本体，例如“帮我分析 prd/<id> 并生成测试用例”，无子命令无参数；`agentic-qa` 仅是终端启动器，不属于用户意图文本。
- 接收自然语言后默认调用 LLM 做意图识别，将用户指令路由到对应的 Workflow（`workflows/`）和 QA 方法库（`skills/`）；LLM 路由失败时降级到确定性路由，不直接中断。
- 路由决策依赖 `workflows/` 中的 SOP 定义和 `prompts/semantic-router-prompt.md` 中的路由指令。
- 路由结果自动附加上下文 `rules/`、`prompts/`、`knowledge/` 和目标 PRD 工作区路径。
- 识别失败时标记「路由未匹配」并回退到确定性默认流程，不伪造匹配结果。
- 不自作主张执行未授权的 Workflow 或写入操作。

### Session 管理 Agent

- 为每次 Runtime 会话创建唯一 `run_id`，写入 `.runtime/runs/<run_id>/`。
- 负责 Graph state 的 Checkpoint 持久化（`.runtime/runs/<run_id>/checkpointer.pkl`），支持运行中断后恢复。
- 运行记录自动序列化至 `.runtime/runs/<run_id>/`，包含输入指令、路由结果、Graph 状态变更和写入摘要。目标 PRD 工作区内同步写入 `runs/<run_id>/` 产物、`runs/latest.yml` 指针和 `runs/index.jsonl` 历史索引。
- 自动写入（不打断用户），无需 `--confirm`、`--approve-write` 等显式确认参数。
- 会话结束时在目标 PRD 的 `workspace.yml` 中记录 `last_runtime_run` 和 `runtime_runs`，状态标记仅表示写入完成，不替代业务审核。

### 当前实现事实

- CLI 主入口是自然语言命令：`python -m runtime.cli "分析 prd/<id> 并生成测试用例"`。
- RAG 调试命令允许作为工程调试入口：`python -m runtime.cli rag status|build|search "query"`。
- 配置入口为 `configs/`，加载顺序为 `configs/config.yaml`、`configs/local.yaml`、`configs/private.yaml`，环境变量仍为最高优先级。
- 当前 PRD 工作区运行产物写入 `prd/<id>/runs/<run_id>/analysis/requirement-analysis.md` 和 `prd/<id>/runs/<run_id>/cases/test-cases.md`。
- 当前 Runtime 运行记录写入 `.runtime/runs/<run_id>/`，其中 `rag.json` 保存本次 RAG query、索引元信息和召回来源。
- RAG 索引默认写入 `.rag_index/`，`manifest.json` 记录内容哈希、Embedding provider/model/dim、向量库、chunk 参数和知识库路径；这些元信息不匹配时必须重建索引。
- 当前生成结果默认是草稿，需要人工评审后才能作为正式 QA 资产。

### 目标态边界

- `artifacts/` 正式产物发布、`reviews/` 结构化审核记录、完整 Review Gate、自动化脚本生成、测试执行、失败分析、Bug 草稿、报告生成、Bot/API/Web 入口属于演进方向。
- 当用户要求实现上述生产级能力时，应先读取 `docs/production-agent-runtime-roadmap.md`，再结合 `workflows/`、`rules/` 和现有 Runtime 代码演进。
- 不得在回复或文档中把目标态能力描述为当前已经完整可用，除非已经通过代码和测试验证。

## 禁止事项

- 不跳过人工审核门。
- 不把未经确认的失败直接定性为真实缺陷。
- 不在需求工作区之外散落 QA 产物。
- 不覆盖人工已审核内容，除非用户明确要求。

## 默认执行约束

- 需求分析、用例、脚本、失败分析、bug、报告都先生成草稿。
- 自动化执行前必须确认环境、账号、数据和影响范围。
- 归档前 metadata 中不得存在 `needs_human_review` 或 `needs_human_confirmation`。
- 不得把完整文件内容粘贴到 Chat 中代替路径、摘要和验收结果。

## Runtime 路线约束

- 当前 Runtime 已提供纯自然语言入口、LLM 语义路由、Session 持久化和自动写入。
- Runtime 读取 `workflows/`、`prompts/`、`rules/`、`skills/`、`knowledge/`，而不是替代这些目录。
- 当需求涉及生产级 Runtime 演进时，应优先读取 `docs/production-agent-runtime-roadmap.md`。
