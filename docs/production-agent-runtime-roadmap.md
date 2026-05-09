# 生产级 Agent 与 LangGraph Runtime 路线

本文档用于明确 Agentic-QA 从“Codex 驱动的标准化 QA 工作台”逐步升级到“轻量 LangGraph Runtime 驱动的生产级 Agent 工作流”的路线。它不推翻现有声明式工作台，而是在现有 `AGENTS.md`、`COMMANDS.md`、`workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/` 和 `prd/` 之上增加可执行编排层。

## 终极目标

Agentic-QA 的终极目标是：

```text
生产级 Human-in-the-loop Agentic QA Workspace
```

它应支持用户用自然语言命令驱动 QA 作业，并通过可审计、可恢复、可检查、可持续迭代的 Agent 工作流完成：

- 需求分析。
- 测试用例生成。
- API 自动化脚本草稿生成。
- UI 自动化脚本草稿生成。
- 测试执行。
- 失败分析。
- Bug 草稿生成。
- QA 报告草稿生成。
- 归档。

AI 只负责生成、执行、整理和辅助判断，最终审核、确认和发布决策仍由人完成。

## 两阶段路线

### 第 1 阶段：Codex 驱动的标准化工作台

第 1 阶段继续把 Agentic-QA 仓库建设成标准化工作台：

```text
用户自然语言命令
  ↓
Codex / ChatGPT / IDE Agent 读取仓库规范
  ↓
COMMANDS.md 路由
  ↓
workflows/ + tasks/ + agents/ + prompts/ + rules/ + skills/ + knowledge/
  ↓
生成或更新 prd/<需求名>/ 对应产物
  ↓
人工审核和确认
```

本阶段重点是：

- 固化命令路由。
- 固化 Workflow、Task、Agent、Prompt、Rules、Skills、Knowledge。
- 固化 PRD 工作区结构。
- 固化产物路径、状态流转和人工审核门。
- 使用成熟工具完成辅助校验和测试执行。

本阶段不要求仓库自行调用 LLM，也不要求内置 Agent Runtime。

### 第 2 阶段：轻量 LangGraph Runtime 驱动

第 2 阶段新增轻量 `runtime/`，将第 1 阶段的声明式资产变成可执行流程：

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

第 2 阶段的重点不是自研大平台，而是用成熟生态补齐生产级能力：

- 用 LangGraph 管理流程、状态、条件跳转、循环修正和人工中断点。
- 用 LangChain / LangChain Core 管理模型调用、Prompt Template、结构化输出和工具封装。
- 用 Pydantic 定义结构化输入输出 Schema。
- 用 Typer / Rich 保持 CLI 交互简洁。
- 用 SQLite 或文件化 checkpoint 作为最小持久化起点。

## LangGraph 与 LangChain 分工

### LangGraph 负责流程和状态

LangGraph 只负责运行时编排，不负责替代仓库里的声明式文档。

它应承担：

- StateGraph 定义。
- 节点执行顺序。
- 条件路由。
- 失败重试。
- 修正循环。
- Human-in-the-loop 中断点。
- Checkpoint 和流程恢复。
- 运行记录和可观测性。

### LangChain 负责模型调用和结构化交互

LangChain 只负责节点内部的模型交互，不负责替代 Workflow。

它应承担：

- PromptTemplate / ChatPromptTemplate。
- 结构化输出。
- Pydantic Schema 绑定。
- LLM Provider 适配。
- 工具封装。
- 检索链和上下文组装。

## 最适合的仓库架构

目标结构如下：

```text
Agentic-QA/
├── AGENTS.md
├── COMMANDS.md
├── workflows/
├── agents/
├── tasks/
├── prompts/
├── rules/
├── skills/
├── knowledge/
├── prd/
├── runtime/
│   ├── graph/
│   │   ├── state.py
│   │   ├── nodes/
│   │   ├── edges.py
│   │   └── app.py
│   ├── chains/
│   │   ├── intent_chain.py
│   │   ├── testcase_chain.py
│   │   └── quality_chain.py
│   ├── tools/
│   │   ├── file_reader.py
│   │   ├── artifact_writer.py
│   │   ├── pytest_runner.py
│   │   └── allure_reader.py
│   ├── schemas/
│   │   ├── intent.py
│   │   ├── testcase.py
│   │   └── quality.py
│   └── cli.py
├── scripts/
├── tests/
└── docs/
```

其中：

- `workflows/`、`tasks/`、`agents/`、`prompts/`、`rules/`、`skills/`、`knowledge/` 是声明式资产。
- `runtime/` 是可选执行引擎。
- `prd/` 是需求级资产工作区。
- `scripts/` 是确定性工程脚本。

## 核心设计原则

最合理的生产级设计是：

```text
外层 LangGraph 固定流程
内层关键生成节点用 Agent
底层文件、执行、状态、权限全部使用确定性代码
```

具体原则：

- 不让 Agent 自由决定写入路径。
- 不让 Agent 自由决定是否跳过审核门。
- 不让 Agent 自由执行高风险命令。
- 不把 Prompt 硬编码在 Python 里。
- 不把 Workflow 全部写死在 Runtime 里。
- Runtime 必须读取仓库已有声明式文档。
- Runtime 的输出必须写回 `prd/<需求名>/` 固定目录。
- Runtime 的关键行为必须可测试、可回放、可审计。

## 节点 Agent 化边界

| 节点 | 是否 Agent 化 | 说明 |
|---|---:|---|
| Command Router | 否 | 使用结构化分类即可 |
| Workflow Selector | 否 | 文件匹配和规则匹配应确定性执行 |
| Context Loader | 否 | 读取文件和组装上下文应确定性执行 |
| Requirement Analyzer | 是 | 需要模型推理和业务规则抽取 |
| Testcase Agent | 是 | 需要测试设计能力 |
| Script Agent | 是 | 需要代码生成和局部修正 |
| Quality Checker | 半 Agent | 规则校验确定性，质量评分可用模型辅助 |
| Revision Node | 是 | 需要根据质量反馈修正产物 |
| Human Review Gate | 否 | 必须显式暂停等待人工确认 |
| Artifact Writer | 否 | 文件写入必须确定路径和状态 |
| Metadata Updater | 否 | 状态流转必须确定性执行 |

## 第一个 Runtime 闭环

不要一开始做全链路。第 2 阶段第一个可运行闭环只做：

```text
生成测试用例
```

推荐最小流程：

```text
intent_router_node
  ↓
prd_context_loader_node
  ↓
testcase_generation_node
  ↓
testcase_quality_check_node
  ↓
revise_testcase_node 或 artifact_writer_node
  ↓
human_review_node
  ↓
metadata_update_node
```

对应命令示例：

```bash
python -m runtime.cli run "帮我生成 prd/sample-login-requirement 需求测试用例"
```

## 推荐执行策略

1. 保留现有声明式工作台。
2. 新增 `runtime/` 最小骨架。
3. 做第一个 LangGraph 流程：测试用例生成。
4. 加入 Human-in-the-loop。
5. 加入持久化和运行记录。
6. 接入真实 QA 工具，例如 pytest、Playwright、Allure。

## 非目标

即使进入第 2 阶段，也不要把项目做成以下形态：

- 完整 Web 平台。
- 自研 LLM Provider。
- 自研大型 WorkflowEngine。
- 自研测试管理系统。
- 自研向量数据库平台。
- 完全无人参与的自动决策系统。

Agentic-QA 的核心仍然是个人专用、人机协同、可审计、可恢复的 QA 工作空间。
