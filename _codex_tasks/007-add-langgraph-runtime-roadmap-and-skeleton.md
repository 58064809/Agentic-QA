# 任务 007：新增 LangGraph Runtime 路线与最小骨架

## 任务目标

在现有 Codex 驱动的 Agentic-QA 标准化工作台基础上，正式引入“第 2 阶段：轻量 LangGraph Runtime”的路线说明和最小代码骨架。

本任务不是推翻现有声明式工作台，而是让仓库进入两阶段路线：

1. 第 1 阶段：继续保留 Codex 驱动，完善 `AGENTS.md`、`COMMANDS.md`、`workflows/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/`、`prd/`。
2. 第 2 阶段：新增轻量 `runtime/`，用 LangGraph 管理流程和状态，用 LangChain 管理模型调用、Prompt Template、结构化输出和工具封装。

最终目标是生产级 Human-in-the-loop Agentic QA Workspace。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 保留现有 Codex 驱动模式，不删除现有声明式文档。
4. 不做 Web 平台、不做数据库系统、不做自研大型 WorkflowEngine。
5. 可以新增轻量 `runtime/`，但必须把它定义为“可选执行引擎”。
6. Runtime 必须读取仓库已有声明式资产，不能把 Prompt、Workflow、Rules 全部硬编码到 Python。
7. 先只做“测试用例生成”一个最小闭环，不要一次性实现所有 QA 流程。
8. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 背景

当前仓库已经完成了标准化 Agentic-QA 工作台雏形：

- `AGENTS.md`：全局 Agent 协作规范。
- `COMMANDS.md`：自然语言命令路由。
- `workflows/`：声明式工作流。
- `agents/`：Agent 角色定义。
- `tasks/`：任务 SOP。
- `prompts/`：Prompt 模板。
- `rules/`：强约束规则。
- `skills/`：测试专业能力说明。
- `knowledge/`：测试知识和模板。
- `prd/`：需求级工作区。
- `scripts/`：确定性工程脚本。

现在需要把项目路线升级为：

```text
Agentic-QA 提供标准化上下文和产物规范
LangGraph 提供稳定流程编排
LangChain 提供模型、Prompt、结构化输出和工具封装
Codex 继续负责代码开发和人工协作施工
```

## 具体任务

### 1. 更新 README

更新 `README.md`，必须表达清楚：

- 当前默认工作模式仍是 Codex 驱动的声明式工作台。
- 项目终极目标是生产级 Human-in-the-loop Agentic QA Workspace。
- 后续允许新增轻量 `runtime/` 作为第 2 阶段可选执行引擎。
- `runtime/` 不替代 `workflows/`、`prompts/`、`rules/`、`skills/`、`knowledge/`，而是读取并执行这些声明式资产。
- LangGraph 负责流程和状态。
- LangChain 负责模型调用和结构化交互。
- 先落地测试用例生成闭环。

建议新增小节：

```markdown
## 生产级 Agent 路线
```

并引用：

```text
docs/production-agent-runtime-roadmap.md
```

### 2. 更新 AGENTS.md

当前 `AGENTS.md` 中“禁止事项”写了“不实现新的 Agent Runtime、工作流引擎、LLM Provider 或平台服务”。

需要改成更准确的两阶段口径：

- 第 1 阶段默认不实现 Runtime。
- 第 2 阶段允许新增轻量 LangGraph Runtime。
- 仍然禁止自研大型 Agent Runtime、LLM Provider、Web 平台和数据库系统。
- Runtime 不得跳过人工审核门。
- Runtime 不得替代声明式资产。

### 3. 更新 COMMANDS.md

补充 Runtime 路线说明：

- Codex 驱动仍然是默认执行方式。
- 后续可通过 `runtime/cli.py` 或 `python -m runtime.cli run "..."` 执行同类自然语言命令。
- Runtime 命令必须复用现有 `COMMANDS.md` 路由表。
- Runtime 仅先支持“生成测试用例”最小闭环。

不要删除现有路由表。

### 4. 新增 Runtime 设计文档

如果尚未存在，新增：

```text
docs/production-agent-runtime-roadmap.md
```

内容至少包括：

- 终极目标。
- 两阶段路线。
- LangGraph 与 LangChain 分工。
- 目标目录结构。
- 核心设计原则。
- 哪些节点可以 Agent 化，哪些必须确定性执行。
- 第一个 Runtime 闭环。
- 非目标。

如果该文件已经存在，只需要检查并按本任务要求补齐。

### 5. 新增 runtime 最小骨架

新增目录：

```text
runtime/
├── __init__.py
├── cli.py
├── graph/
│   ├── __init__.py
│   ├── app.py
│   ├── edges.py
│   ├── state.py
│   └── nodes/
│       ├── __init__.py
│       ├── intent_router_node.py
│       ├── context_loader_node.py
│       ├── testcase_generation_node.py
│       ├── quality_check_node.py
│       ├── revision_node.py
│       ├── artifact_writer_node.py
│       ├── human_review_node.py
│       └── metadata_update_node.py
├── chains/
│   ├── __init__.py
│   ├── intent_chain.py
│   ├── testcase_chain.py
│   └── quality_chain.py
├── schemas/
│   ├── __init__.py
│   ├── intent.py
│   ├── testcase.py
│   └── quality.py
└── tools/
    ├── __init__.py
    ├── file_reader.py
    ├── artifact_writer.py
    ├── pytest_runner.py
    └── allure_reader.py
```

注意：

- 本任务只要求最小骨架，可以先不接真实 LLM。
- 不要为了骨架引入不可运行的大量复杂代码。
- `runtime/cli.py` 至少要有 `run` 命令入口。
- 未配置 LLM 时，CLI 应明确提示“Runtime 骨架已就绪，但模型调用未配置”，不能假装生成成功。
- 可以先把 LangGraph / LangChain 依赖作为可选依赖或待接入说明，不要让现有 CI 因缺少 API Key 或模型配置失败。

### 6. 新增最小状态与 Schema

建议新增：

`runtime/graph/state.py`

包含类似：

```python
from typing import TypedDict

class QAWorkflowState(TypedDict, total=False):
    user_input: str
    intent: dict
    prd_name: str
    workflow_name: str
    loaded_files: list[str]
    requirement_text: str
    rules_text: str
    skills_text: str
    prompt_text: str
    draft_artifact: str
    quality_result: dict
    review_status: str
    output_path: str
    errors: list[str]
```

`runtime/schemas/intent.py` 至少包含：

- command。
- prd_name。
- confidence。
- missing_info。

`runtime/schemas/quality.py` 至少包含：

- passed。
- score。
- problems。
- suggestions。

### 7. 新增测试

新增或更新测试：

```text
tests/unit/test_runtime_skeleton.py
```

至少覆盖：

- `runtime.cli` 可以导入。
- `QAWorkflowState` 可以导入。
- Intent / Quality Schema 可以创建实例。
- 未配置 LLM 时，run 命令不会误报成功。

如果当前项目未安装 LangGraph / LangChain，不要让测试强依赖它们。

### 8. 更新 pyproject.toml

可以新增可选依赖组，例如：

```toml
[project.optional-dependencies]
runtime = [
  "langgraph>=0.2",
  "langchain-core>=0.3",
  "pydantic>=2",
]
```

如果已有依赖结构不同，按现有风格调整。

注意：

- 不要把所有运行时依赖强塞进默认 dependencies，避免现有快速校验变慢或失败。
- `pydantic` 如果 Schema 测试需要，可以放默认依赖，也可以先用 dataclass 替代。优先保持简单稳定。

### 9. 更新文档一致性检查

如 `scripts/validate_docs_consistency.py` 已存在，需要补充检查：

- `docs/production-agent-runtime-roadmap.md` 存在。
- `README.md` 包含“生产级 Agent 路线”或类似标题。
- `AGENTS.md` 不应再绝对禁止轻量 Runtime。
- 新增 `runtime/` 后，检查核心 runtime 文件是否存在。

注意保持轻量，不要做复杂解析器。

## 验收命令

执行：

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

Commit message：

```text
feat: add langgraph runtime roadmap and skeleton
```

## 完成后的回复要求

必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复，只输出摘要，不粘贴完整文件或完整 diff。
