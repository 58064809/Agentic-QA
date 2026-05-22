# 生产级 Agent Runtime 路线图

## 目标说明

Agentic-QA 的终极目标是建设生产级 Agentic QA 系统。生产级不是一开始自研平台，而是逐步具备可路由命令、声明式 QA 工作流、可复用 Agent 角色、可追踪 PRD 产物、Human-in-the-loop 门禁、可恢复 Runtime、运行记录和真实 QA 工具接入能力。

当前仓库仍以第 1 阶段为默认模式：Codex / ChatGPT / IDE Agent 读取仓库声明式资产并生成 QA 产物。第 2 阶段才引入轻量 LangGraph Runtime；它增强当前工作台，不替代当前工作台。

核心边界：

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

## 两阶段路线

### 第 1 阶段：Codex 驱动的标准化工作台

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

### 第 2 阶段：LangGraph Runtime 驱动的轻量执行引擎

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
Requirement Normalizer：必要时将 Word/PDF/TXT/HTML 需求源文件转换为 requirement.md
  ↓
Image Reference Detector：检测 requirement.md 中的图片/原型图痕迹，只 warning，不分析图片内容
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

## 总体流程图

```text
用户命令
  ↓
Command Router
  ↓
Workflow Selector
  ↓
Context Loader
  ↓
Agent / Chain Node
  ↓
Quality Checker
  ↓
Human Review Gate
  ↓
Artifact Writer
  ↓
Metadata Updater
  ↓
PRD 工作区产物
```

## 分工边界

### LangGraph 负责

- 流程编排。
- 节点状态传递。
- 条件路由。
- 循环修正。
- Human-in-the-loop。
- Checkpoint / 持久化。
- 可恢复执行。
- 运行记录和可观测性。

### LangChain 负责

- 模型调用封装。
- `PromptTemplate` / `ChatPromptTemplate`。
- 结构化输入输出。
- Pydantic Schema。
- Output Parser。
- 工具封装。
- RAG / 检索链。

### Agentic-QA 负责

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

### Codex 负责

- 按任务包修改代码和文档。
- 读取仓库上下文。
- 生成具体实现。
- 执行校验命令。
- 按完成回执模板汇报。

## 推荐 Runtime 目录结构

后续 Runtime 骨架建议如下。本任务只做路线图和文档对齐，具体 Runtime 实现在后续任务中完成。

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

## 第一条落地链路：测试用例生成

第 2 阶段第一条闭环优先做测试用例生成，不直接做全链路平台。

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

要求：

- Runtime 必须读取 `workflows/02-testcase-generation-workflow.md`、`prompts/testcase-design-prompt.md`、`rules/testcase-rules.md`、`skills/test-design-skill.md` 和 `knowledge/templates/testcase-template.md`。
- Runtime 不允许把 Prompt、Rules、Skills 全部硬编码进 Python。
- Artifact Writer 只能写入 `prd/<需求名>/20-testcases/testcases.md`。
- 写入、执行、归档动作必须经过 Human Review Gate。

## 生产级能力清单

- 自然语言命令路由。
- 声明式 Workflow 读取。
- PRD 上下文加载。
- 需求正文归一化：Word/PDF/TXT/HTML 到 `requirement.md`。
- 图片引用检测：发现图片/原型图痕迹时 warning，并提示人工确认图片中是否有未写入正文的信息。
- 结构化状态对象。
- Agent 生成节点。
- 质量检查和修正循环。
- Human-in-the-loop 暂停点。
- Artifact Writer 确定性写入。
- Metadata 状态更新。
- Checkpoint 和恢复执行。
- 运行记录和可观测性。
- pytest、Playwright、Allure、日志分析和报告生成接入。

## 不做事项

- 不直接实现完整 LangGraph Runtime。
- 不自研复杂 Agent 调度器。
- 不自研 WorkflowEngine。
- 不自研 LLM Provider。
- 不新建 Web 平台。
- 不引入数据库或向量库作为本阶段前置。
- 不替换现有 Codex 驱动工作流。
- 不把 Prompt / Rules / Skills 全部硬编码进 Python。

## 后续施工任务拆分

1. `008-bootstrap-langgraph-runtime-skeleton.md`：新增 Runtime 最小骨架，只实现最小可运行闭环。
2. `009-runtime-testcase-generation-graph.md`：实现测试用例生成 Graph。
3. `010-runtime-human-review-gate.md`：加入 Human-in-the-loop 暂停和确认机制。
4. `011-runtime-persistence-and-run-records.md`：加入 Checkpoint、运行记录和状态恢复。
5. `012-runtime-qa-tool-integration.md`：接入 pytest、Playwright、Allure 和日志分析工具。

当前进展：StateGraph 编排已接入测试用例生成最小流程；011 已加入本地运行记录；012 已打通需求分析草稿、测试用例草稿和 MVP 连续链路；012A 已把默认输出和质量门提升到评审级；012B 已补强质量门，低质量 Skeleton、空待确认问题、少量示例用例、非法优先级和额外“用例类型”列不能误通过；013 已接入 MarkItDown，将目标 PRD 工作区内的 Word/PDF/TXT/HTML 等需求源文件转换为 `requirement.md` 后再分析；016 已废弃 `prototype-notes.md` 输入链路，Runtime 只分析 `requirement.md` 和 `api-doc.md` 文本，检测到图片/原型图引用时 warning，并在待确认问题中提示人工确认图片是否包含未写入正文的信息。当前不分析图片二进制，不接视觉模型，也不基于图片内容编造字段、按钮、布局或交互。LLM 默认关闭，仅通过 `--use-llm` 显式启用，并只读取本地环境变量；OpenAI-compatible 调用优先使用 `responses.create`，`chat.completions.create` fallback 默认关闭，仅在本地设置 `FREEMODEL_ENABLE_CHAT_FALLBACK=true` 时启用。Runtime Graph 已加入 checkpointer 和 `thread_id`，`human_review_node` 使用 `interrupt` 暂停，CLI 支持 `approve`、`reject`、`resume`，审批通过后才允许 writer 写入；运行状态、Graph state 和 checkpointer 写入 `.runtime/runs/<run_id>/`。更复杂的多轮审批和可视化 Human-in-the-loop 仍在后续任务中完成。
