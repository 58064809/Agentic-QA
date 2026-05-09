# 任务 007：对齐生产级 Agent Runtime 路线图与文档体系

## 任务目标

在 001~006 已完成 Agentic-QA 标准化工作台、命令路由、声明式工作流、规则、模板和轻量校验能力之后，本任务将仓库定位升级为更清晰的两阶段路线：

1. 第 1 阶段：继续把 Agentic-QA 做成标准化 QA 工作台，由 Codex / ChatGPT / IDE Agent 驱动执行。
2. 第 2 阶段：新增轻量 LangGraph Runtime，由 LangGraph 负责流程和状态，由 LangChain 负责模型调用、Prompt 模板、结构化输入输出和工具封装。

本任务重点是更新仓库文档、路线图、架构说明和 Codex 执行规则，让 Codex 明确后续怎么开发，不要求本次直接实现完整 LangGraph Runtime。

最终目标是：

> Agentic-QA 提供标准化上下文和产物规范；LangGraph 提供稳定流程编排；LangChain 提供模型、Prompt、结构化输出和工具封装；Codex 继续负责代码开发和人工协作施工。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 继续坚持“尽量不自研”：不要自研复杂 Agent 调度器、WorkflowEngine、LLM Provider、Web 平台、数据库系统或向量库系统。
4. 本任务可以新增 `runtime/` 目录规划文档，但不要在本任务中写完整 Runtime 实现。
5. 本任务可以新增最小占位文件，例如 `runtime/README.md`、`runtime/graph/README.md` 等，但不要引入 LangGraph / LangChain 依赖，除非同时完成可运行最小闭环和测试。
6. 现阶段不要破坏已有 Codex 驱动模式；LangGraph Runtime 是第 2 阶段增强，不是替代当前工作台。
7. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 背景判断

当前 Agentic-QA 已经明确不是传统自动化测试平台，也不是一开始自研 LLM Agent Runtime，而是：

> Command-routed Human-in-the-loop Agentic QA Workspace

也就是通过 `AGENTS.md`、`COMMANDS.md`、`workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/`、`prd/` 等目录，为 Codex / ChatGPT / Cursor / Claude Code 等 AI Coding Agent 提供可执行的 QA 工作上下文。

但为了达到“生产级 Agent”的终极目标，后续需要逐步引入轻量 Runtime：

- 外层 LangGraph 固定流程。
- 内层关键生成节点可以是 Agent。
- 底层文件、执行、状态、权限必须使用确定性代码。
- Human-in-the-loop 作为关键门禁，不让 AI 直接替代最终判断。
- 所有产物必须写回 `prd/<需求名>/xx-xxx/`。
- 所有状态必须更新到 `metadata.yml` 或对应运行记录。

## 需要统一写入文档的核心结论

请把以下结论沉淀到合适文档中，不要只写在本任务文件里。

### 1. 终极目标

Agentic-QA 的终极目标是建设生产级 Agentic QA 系统。

生产级不是指一开始就自研平台，而是逐步具备：

- 可路由的自然语言命令。
- 可声明的 QA 工作流。
- 可复用的 Agent 角色、Prompt、Rules、Skills、Knowledge。
- 可追踪的 PRD 级产物工作区。
- 可审核的 Human-in-the-loop 门禁。
- 可运行、可恢复、可观测的轻量 Runtime。
- 可接入真实 QA 工具，例如 pytest、Playwright、Allure、日志分析和报告生成。

### 2. 两阶段路线

#### 第 1 阶段：Codex 驱动的标准化工作台

目标：让 Codex / ChatGPT / IDE Agent 能根据仓库规则完成 QA 任务。

核心资产：

- `AGENTS.md`
- `COMMANDS.md`
- `workflows/`
- `agents/`
- `tasks/`
- `prompts/`
- `rules/`
- `skills/`
- `knowledge/`
- `prd/`
- `scripts/`
- `tests/`

执行方式：

```text
用户自然语言命令
  ↓
Codex 读取 AGENTS.md / COMMANDS.md
  ↓
匹配 workflow / task / agent / prompt / rules / skills / knowledge
  ↓
读取 prd/<需求名>/ 上下文
  ↓
生成或修改产物
  ↓
人工审核
  ↓
继续执行或归档
```

#### 第 2 阶段：LangGraph Runtime 驱动的轻量执行引擎

目标：用成熟 Agent 编排框架承接流程、状态、条件路由、循环修正、Human-in-the-loop、持久化和运行记录。

执行方式：

```text
用户自然语言命令
  ↓
Command Router：识别任务类型
  ↓
Workflow Selector：匹配 workflows/*.md
  ↓
Context Loader：加载 PRD、Rules、Skills、Prompt、Knowledge
  ↓
Requirement Analyzer / Testcase Agent / Script Agent
  ↓
Quality Checker：质量检查
  ↓
条件判断：
  ├── 通过 → Artifact Writer
  └── 不通过 → Revision Node
  ↓
Human Review Gate
  ↓
写回 prd/<需求名>/xx-xxx/
  ↓
更新 metadata.yml 状态
```

### 3. LangGraph、LangChain、Agentic-QA、Codex 的边界

必须明确写入文档：

```text
不是 LangChain 替代 Agentic-QA
不是 LangGraph 替代 workflows/
不是 Agent 替代所有确定性代码

而是：

Agentic-QA 提供标准化上下文和产物规范
LangGraph 提供稳定流程编排
LangChain 提供模型、Prompt、结构化输出和工具封装
Codex 继续负责代码开发和人工协作施工
```

### 4. LangGraph 与 LangChain 分工

LangGraph 负责：

- 流程编排。
- 节点状态传递。
- 条件路由。
- 循环修正。
- Human-in-the-loop。
- Checkpoint / 持久化。
- 可恢复执行。
- 运行记录和可观测性。

LangChain 负责：

- 模型调用封装。
- `PromptTemplate` / `ChatPromptTemplate`。
- 结构化输入输出。
- Pydantic Schema。
- Output Parser。
- 工具封装。
- RAG / 检索链。

Agentic-QA 负责：

- 工作台目录结构。
- 命令路由表。
- 声明式 Workflow。
- Agent 角色说明。
- Task SOP。
- Prompt 模板。
- Rules 强约束。
- Skills 能力说明。
- Knowledge 知识库。
- PRD 级产物归档。

Codex 负责：

- 按任务包修改代码和文档。
- 读取仓库上下文。
- 生成具体实现。
- 执行校验命令。
- 按完成回执模板汇报。

## 具体任务

### 1. 更新 README.md

在 README 中补充或调整：

1. 项目终极目标：生产级 Agentic QA 系统。
2. 当前阶段：Codex 驱动的标准化工作台。
3. 下一阶段：轻量 LangGraph Runtime。
4. 说明 LangGraph / LangChain / Agentic-QA / Codex 的边界。
5. 说明不要一开始就重写成 Runtime，必须先保留声明式资产。
6. 保留已有快速开始、校验命令和 Codex 使用方式。

README 中应出现以下核心表达：

```text
第 1 阶段：Codex 驱动的标准化工作台
第 2 阶段：LangGraph Runtime 驱动的轻量执行引擎
外层 LangGraph 固定流程，内层关键生成节点用 Agent，底层文件、执行、状态、权限全部使用确定性代码
```

### 2. 新增或更新架构文档

优先新增：

`docs/architecture/production-agent-runtime-roadmap.md`

如果 `docs/architecture/` 不存在，请创建。

文档至少包含：

1. 目标说明。
2. 两阶段路线。
3. 总体流程图，使用文本图即可。
4. LangGraph / LangChain / Agentic-QA / Codex 边界。
5. 推荐 Runtime 目录结构。
6. 第一条落地链路：测试用例生成。
7. 生产级能力清单。
8. 不做事项。
9. 后续施工任务拆分。

推荐 Runtime 目录结构写成：

```text
runtime/
├── graph/
│   ├── state.py
│   ├── nodes/
│   ├── edges.py
│   └── app.py
├── chains/
│   ├── intent_chain.py
│   ├── testcase_chain.py
│   └── quality_chain.py
├── tools/
│   ├── file_reader.py
│   ├── artifact_writer.py
│   ├── pytest_runner.py
│   └── allure_reader.py
├── schemas/
│   ├── intent.py
│   ├── testcase.py
│   └── quality.py
└── cli.py
```

但要说明：本任务只做路线图和文档对齐，具体 Runtime 实现在后续任务中完成。

### 3. 更新 AGENTS.md

补充 Codex 执行原则：

1. 当前默认执行模式仍然是 Codex 驱动的标准化工作台。
2. 当用户要求“生产级 Agent / LangGraph Runtime / Runtime 驱动”时，Codex 应优先查看 `docs/architecture/production-agent-runtime-roadmap.md`。
3. Codex 不得把 LangGraph Runtime 和现有声明式工作台对立起来。
4. Codex 不得把 Prompt、Rules、Skills 全部硬编码进 Python。
5. Codex 后续实现 Runtime 时，应让 Runtime 读取 `workflows/`、`prompts/`、`rules/`、`skills/`、`knowledge/`，而不是替代这些目录。
6. Codex 修改 Runtime 前，必须明确是否属于第 1 阶段文档工作台，还是第 2 阶段 Runtime 能力。

### 4. 更新 COMMANDS.md

补充生产级 Runtime 相关命令路由，例如：

| 用户命令示例 | 任务类型 | 应读取文档 | 说明 |
|---|---|---|---|
| 设计生产级 Agent 架构 | architecture_planning | `docs/architecture/production-agent-runtime-roadmap.md` | 只做架构和路线，不直接实现完整 Runtime |
| 新增 LangGraph Runtime 骨架 | runtime_bootstrap | `docs/architecture/production-agent-runtime-roadmap.md` | 创建最小 Runtime 目录和入口 |
| 实现测试用例生成 Graph | runtime_testcase_graph | `workflows/02-testcase-generation-workflow.md` | 第一条 Runtime 闭环 |
| 加入 Human-in-the-loop | runtime_human_gate | `rules/review-gate-rules.md` | 对写入、执行、归档等动作加人工门禁 |
| 加入 Runtime 持久化 | runtime_persistence | `docs/architecture/production-agent-runtime-roadmap.md` | Checkpoint、运行记录、状态恢复 |

要求不要删除已有命令路由，只新增或补充。

### 5. 更新 workflows 或新增 Runtime 工作流文档

新增：

`workflows/10-runtime-testcase-generation-workflow.md`

用于描述第 2 阶段第一条 Runtime 闭环。

至少包含：

- 适用场景。
- 触发命令。
- 主流程。
- 节点定义。
- 输入状态。
- 输出状态。
- 必须读取的文件。
- Human Review Gate。
- Artifact Writer 规则。
- 状态更新规则。
- 验收标准。

主流程写成：

```text
intent_router_node
  ↓
workflow_selector_node
  ↓
context_loader_node
  ↓
testcase_generation_node
  ↓
testcase_quality_check_node
  ↓
条件判断：
  ├── pass → human_review_node
  └── fail → testcase_revision_node → testcase_quality_check_node
  ↓
artifact_writer_node
  ↓
metadata_update_node
```

### 6. 更新 docs/roadmap 或新增路线图

如果已有 `docs/roadmap.md`，更新它。

如果没有，新增：

`docs/roadmap.md`

路线按以下顺序写：

1. 001：保留并完善现有声明式工作台。
2. 002：新增 Runtime 最小骨架。
3. 003：做第一个 LangGraph 流程：测试用例生成。
4. 004：加入 Human-in-the-loop。
5. 005：加入持久化和运行记录。
6. 006：接入真实 QA 工具。

### 7. 可选：新增 Runtime 占位说明

允许新增：

- `runtime/README.md`
- `runtime/graph/README.md`
- `runtime/chains/README.md`
- `runtime/tools/README.md`
- `runtime/schemas/README.md`

这些文件只做说明，不写伪装成已完成的代码。

`runtime/README.md` 必须明确：

1. 当前 Runtime 处于规划或骨架阶段。
2. 第一个实现目标是测试用例生成 Graph。
3. Runtime 必须读取现有声明式资产。
4. Runtime 不允许硬编码 Prompt / Rules / Skills。
5. Runtime 的写入、执行、归档动作必须经过 Human Review Gate。

### 8. 更新校验脚本覆盖范围

如果当前 `scripts/validate_docs_consistency.py` 已存在，则轻微更新检查项：

1. 如果新增了 `docs/architecture/production-agent-runtime-roadmap.md`，应检查它存在。
2. 如果新增了 `workflows/10-runtime-testcase-generation-workflow.md`，应检查它存在。
3. 如果新增了 `docs/roadmap.md`，应检查它存在。
4. 不要求本任务强制检查所有 Runtime 占位目录，避免后续迭代时过度约束。

如果脚本不存在，不要为了本任务强行实现复杂脚本；只按已有仓库状态处理。

## 推荐文档结构

完成后，仓库应至少体现：

```text
README.md
AGENTS.md
COMMANDS.md
workflows/10-runtime-testcase-generation-workflow.md
docs/roadmap.md
docs/architecture/production-agent-runtime-roadmap.md
_codex_tasks/007-align-production-agent-runtime-roadmap.md
```

可选体现：

```text
runtime/README.md
runtime/graph/README.md
runtime/chains/README.md
runtime/tools/README.md
runtime/schemas/README.md
```

## 不做事项

本任务不要做：

1. 不要直接实现完整 LangGraph Runtime。
2. 不要引入数据库。
3. 不要引入向量库。
4. 不要新建 Web 平台。
5. 不要替换现有 Codex 驱动工作流。
6. 不要把 Prompt / Rules / Skills 全部硬编码进 Python。
7. 不要创建新分支。
8. 不要删除已有 001~006 任务沉淀。

## 验收命令

完成后尽量执行：

```bash
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/sample-login-requirement
python scripts/run_pytest.py
pytest
ruff check .
```

如果某个命令未执行，完成回执中必须说明原因，不能写成通过。

## 提交要求

直接提交到 `master`。

建议 Commit message：

```text
docs: align production agent runtime roadmap
```

## 完成后的回复要求

必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复，只输出摘要，不粘贴完整文件或完整 diff。

完成回执必须包含：

1. 变更摘要。
2. 修改文件列表。
3. 是否已更新 README / AGENTS / COMMANDS / roadmap / architecture 文档。
4. 是否新增 Runtime 路线说明或占位目录。
5. 已执行的验收命令和结果。
6. 未执行命令及原因。
7. 待人工确认点。
8. 下一步建议。

## 下一任务预告

007 完成后，下一步建议创建：

`008-bootstrap-langgraph-runtime-skeleton.md`

目标是正式新增 Runtime 最小骨架，但只实现最小可运行闭环，不做全量平台化。