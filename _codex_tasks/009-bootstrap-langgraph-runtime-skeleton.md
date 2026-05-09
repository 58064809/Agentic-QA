# 任务 009：新增 LangGraph Runtime 最小骨架

## 任务目标

在 007/008 已完成生产级 Agent Runtime 路线图和规则冲突修复后，本任务正式进入第 2 阶段，但只做**轻量 Runtime 最小骨架**，不要一次性实现完整 Agent 平台。

本任务的目标是新增一个可运行、可测试、可扩展的 `runtime/` 骨架，让后续可以逐步接入 LangGraph、LangChain、Human-in-the-loop、持久化和真实 QA 工具。

本任务不是要做完整 Runtime，也不是要接入真实 LLM。009 只实现：

1. Runtime 目录结构。
2. 最小 CLI 入口。
3. 测试用例生成 Graph 的 dry-run 流程骨架。
4. 确定性节点：命令识别、workflow 选择、上下文加载、质量检查、写入门禁。
5. 默认不写文件，只有显式授权才允许写入草稿。
6. 单元测试覆盖核心节点和 CLI dry-run 行为。

最终形成一个后续 010 可以继续接入真实 LangGraph `StateGraph` 的基础。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 允许新增 `runtime/` Python 包，但不要新增 Web 平台、数据库、向量库或复杂服务。
4. 本任务不要接入真实 LLM，不读取 API Key，不调用 OpenAI / Anthropic / LangChain ChatModel。
5. 本任务不要强制引入 LangGraph / LangChain 依赖；可以预留 adapter 位置，但 CI 不应依赖外部模型或网络。
6. Runtime 必须复用现有声明式资产：`workflows/`、`prompts/`、`rules/`、`skills/`、`knowledge/`，不得把 Prompt、Rules、Skills 全部硬编码进 Python。
7. 默认执行必须是 dry-run，不允许默认覆盖 `prd/<需求名>/20-testcases/testcases.md`。
8. 只有传入明确参数，例如 `--approve-write`，才允许写入草稿文件。
9. 写入草稿时必须标记为 `needs_human_review`，不得绕过人工审核门。
10. 不允许连接真实业务环境，不允许执行真实测试，不允许归档。
11. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 背景依据

当前仓库定位是：

```text
Agentic-QA 提供标准化上下文和产物规范
LangGraph 提供稳定流程编排
LangChain 提供模型、Prompt、结构化输出和工具封装
Codex 继续负责代码开发和人工协作施工
```

009 要做的是把第二阶段的代码入口先立起来，但仍然保持轻量、可控、可测试。

必须优先读取：

```text
AGENTS.md
COMMANDS.md
docs/architecture/production-agent-runtime-roadmap.md
docs/roadmap.md
workflows/10-runtime-testcase-generation-workflow.md
workflows/02-testcase-generation-workflow.md
rules/review-gate-rules.md
rules/artifact-path-rules.md
rules/testcase-rules.md
knowledge/templates/testcase-template.md
```

## 推荐新增目录结构

新增：

```text
runtime/
├── __init__.py
├── README.md
├── cli.py
├── graph/
│   ├── __init__.py
│   ├── app.py
│   ├── state.py
│   └── nodes/
│       ├── __init__.py
│       ├── intent_router.py
│       ├── workflow_selector.py
│       ├── context_loader.py
│       ├── testcase_generation.py
│       ├── quality_checker.py
│       ├── human_review.py
│       ├── artifact_writer.py
│       └── metadata_update.py
├── schemas/
│   ├── __init__.py
│   └── runtime_result.py
└── tools/
    ├── __init__.py
    ├── file_reader.py
    └── artifact_writer.py
```

如果 Codex 认为文件数量过多，可以合并少量节点文件，但必须保留清晰边界：

- `state.py`：状态对象。
- `app.py`：流程编排入口。
- `cli.py`：命令行入口。
- `tools/`：确定性文件读写工具。
- `nodes/`：各节点逻辑。

## Runtime 最小流程

本任务只实现测试用例生成 dry-run 流程：

```text
用户自然语言命令
  ↓
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
human_review_node
  ↓
artifact_writer_node
  ↓
metadata_update_node
```

注意：

- 这里的 `testcase_generation_node` 暂时不调用 LLM。
- 可以生成一个“测试用例草稿骨架”，但必须明确标记为 Runtime Skeleton 生成的草稿，不代表最终 AI 用例质量。
- 010 或后续任务再接入 LangGraph / LangChain / LLM。

## 状态对象要求

建议在 `runtime/graph/state.py` 中定义 `QAWorkflowState`，可以使用 `dataclass` 或 `TypedDict`。

至少包含：

```python
user_input: str
prd_path: str
intent: str | None
workflow_files: list[str]
loaded_files: dict[str, str]
draft_artifact: str | None
quality_errors: list[str]
review_status: str
output_path: str | None
dry_run: bool
approve_write: bool
errors: list[str]
```

要求：

- 状态对象必须可单元测试。
- 不要依赖外部服务。
- 不要在状态中保存敏感信息。

## CLI 要求

新增 `runtime/cli.py`，支持：

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
```

默认 dry-run：

- 只打印将要读取的文件。
- 只打印将要执行的节点。
- 只打印目标输出路径。
- 不写入文件。

显式写入：

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement --approve-write
```

写入要求：

- 只能写入 `prd/<id>/20-testcases/testcases.md`。
- 如果目标文件已存在，默认不得覆盖；除非另外提供 `--force`，但本任务可以不实现 `--force`。
- 写入内容必须包含：
  - Runtime Skeleton 标识。
  - `needs_human_review` 状态。
  - 来源文件列表。
  - 待人工确认项。
- 写入后不得自动进入 API/UI 自动化脚本生成。

建议 CLI 输出中文摘要，避免输出完整大文件。

## 节点实现要求

### 1. intent_router_node

确定性识别测试用例生成意图。

命中关键词示例：

```text
测试用例
用例
testcase
test case
生成用例
设计用例
```

若未命中，返回错误：

```text
当前 Runtime Skeleton 仅支持测试用例生成 dry-run。
```

### 2. workflow_selector_node

固定选择：

```text
workflows/10-runtime-testcase-generation-workflow.md
workflows/02-testcase-generation-workflow.md
```

并校验文件存在。

### 3. context_loader_node

至少加载：

```text
AGENTS.md
COMMANDS.md
docs/architecture/production-agent-runtime-roadmap.md
workflows/10-runtime-testcase-generation-workflow.md
workflows/02-testcase-generation-workflow.md
prompts/testcase-design-prompt.md
rules/testcase-rules.md
rules/review-gate-rules.md
rules/artifact-path-rules.md
skills/test-design-skill.md
knowledge/templates/testcase-template.md
prd/<id>/metadata.yml
prd/<id>/requirement.md
```

如果 `prd/<id>/10-analysis/requirement-analysis.md` 存在，也加载；不存在则给出 warning，但不要直接失败。

### 4. testcase_generation_node

暂时不调用 LLM。

可以生成一个结构化草稿骨架，例如：

```markdown
# 测试用例草稿

> 状态：needs_human_review
> 来源：Runtime Skeleton dry-run / approve-write
> 注意：当前内容为 Runtime 最小骨架生成，不代表最终 AI 生成质量。

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
| 待补充：基于需求主流程生成 | P0 | 待人工确认 | 待接入 LangChain 后生成 | 待人工确认 |
```

必须符合用户偏好的用例列结构：

```text
标题｜优先级｜前置条件｜测试步骤｜预期结果
```

### 5. testcase_quality_check_node

至少检查：

- 草稿非空。
- 包含 `needs_human_review`。
- 包含用例表头：`标题`、`优先级`、`前置条件`、`测试步骤`、`预期结果`。
- 输出路径位于目标 PRD 工作区。

### 6. human_review_node

当前先实现为状态门：

- dry-run：显示“需要人工审核，不写入”。
- approve-write：允许写入草稿，但状态仍为 `needs_human_review`。

不要实现复杂交互式审批。

### 7. artifact_writer_node

- dry-run 时不写文件。
- approve-write 时写入 `20-testcases/testcases.md`。
- 如果文件已存在，默认失败并提示人工确认，不覆盖。

### 8. metadata_update_node

本任务可以只做 dry-run 输出，不强制改 `metadata.yml`。

如果实现 metadata 更新，必须：

- 只在 `--approve-write` 时执行。
- 保留已有字段。
- 不破坏 YAML 结构。
- 明确将测试用例产物状态标记为 `needs_human_review`。

为降低风险，本任务建议暂时不修改 metadata，只在 CLI 输出中提示“后续任务补充 metadata update”。

## pyproject 要求

如果新增 `runtime/` Python 包后，当前 `pyproject.toml` 的 setuptools 配置无法包含包，请更新配置。

建议：

```toml
[tool.setuptools.packages.find]
include = ["runtime*"]
```

但不要破坏现有 `pip install -e .`。

## README / 文档更新要求

更新 `runtime/README.md`，说明：

1. 当前 Runtime 处于最小骨架阶段。
2. 009 不接入真实 LLM。
3. 009 不强制引入 LangGraph / LangChain 依赖。
4. 默认 dry-run，不写入文件。
5. `--approve-write` 才允许写入测试用例草稿。
6. 写入后仍然必须人工审核。
7. 后续 010 才继续接入真实 LangGraph 流程。

轻微更新根 `README.md`，补充 Runtime Skeleton 的使用命令：

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
```

不要把 README 写成 Runtime 已经生产可用。

## 文档一致性校验更新

更新 `scripts/validate_docs_consistency.py`：

- 将 `runtime/README.md` 纳入核心文件检查。
- 将 `runtime/` 纳入核心目录检查。
- 不需要强制检查所有节点文件，避免后续迭代过度约束。

同步更新对应单元测试的 minimal repo 构造。

## 单元测试要求

新增测试文件，例如：

```text
tests/unit/test_runtime_skeleton.py
```

至少覆盖：

1. `intent_router_node` 能识别“生成测试用例”。
2. 不支持的意图会返回错误。
3. `context_loader_node` 能加载 sample PRD 必要文件。
4. dry-run 不写入 `testcases.md`。
5. `--approve-write` 在目标文件不存在时可以写入草稿。
6. 目标文件已存在时，默认不覆盖。
7. 质量检查能发现缺少 `needs_human_review` 或缺少表头的问题。

如果测试 CLI 比较麻烦，可以先测试 `run_testcase_generation_workflow()` 这类函数，再补一个轻量 CLI help 测试。

## 验收命令

完成后尽量执行：

```bash
python -m runtime.cli --help
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/sample-login-requirement
python scripts/run_pytest.py
pytest
ruff check .
```

如果执行了 `--approve-write`，请注意不要污染已存在的 sample 正式产物；可以在临时 PRD 工作区或测试临时目录里验证写入能力。

如果某个命令未执行，完成回执中必须说明原因，不能写成通过。

## 不做事项

本任务不要做：

1. 不接入真实 LangGraph `StateGraph`，可以预留后续接入点。
2. 不接入真实 LangChain ChatModel。
3. 不调用外部模型。
4. 不读取 API Key。
5. 不实现复杂持久化。
6. 不实现数据库。
7. 不实现 Web UI。
8. 不执行真实业务测试。
9. 不生成 API/UI 自动化脚本。
10. 不归档需求。
11. 不覆盖人工已审核内容。

## 提交要求

直接提交到 `master`。

建议 Commit message：

```text
feat: bootstrap runtime skeleton
```

## 完成后的回复要求

必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复，只输出摘要，不粘贴完整文件或完整 diff。

完成回执必须包含：

1. 变更摘要。
2. 修改文件列表。
3. Runtime 新增目录说明。
4. CLI 使用命令。
5. dry-run 是否不写文件。
6. `--approve-write` 写入规则说明。
7. 已执行的验收命令和结果。
8. 未执行命令及原因。
9. 待人工确认点。
10. 下一步建议。

## 下一步预告

009 完成并审核通过后，下一任务建议：

```text
010-integrate-langgraph-stategraph.md
```

目标：在 009 骨架基础上接入真实 LangGraph `StateGraph`，但仍不接入真实 LLM。