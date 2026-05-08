# 任务 002：目录与核心文件对齐修复

## 一、任务目标

基于当前 `master` 分支已有的 Agentic-QA 工作区成果，执行一次目录、核心文件、路径、状态、引用关系的全面对齐修复。

本任务不是重建项目，也不是引入新的 Runtime，而是确保当前仓库严格对齐以下定位：

**Command-routed Human-in-the-loop Agentic QA Workspace**

中文定位：**指令路由型人机协同 Agentic QA 工作空间**。

核心模式：

```text
AI 生成 -> 人审核 -> AI 执行 -> 人确认 -> AI 归档
```

## 二、硬性要求

1. 直接在 `master` 分支修改，不创建新分支。
2. 文档尽量使用中文。
3. 尽量不自研。
4. 不要创建 `agentic_qa/`、`src/agentic_qa/`、`BaseAgent`、`WorkflowEngine`、`LLM Provider`、`LangGraph`、`LangChain`、`LiteLLM` 等运行时结构。
5. 工程脚本只放 `scripts/`。
6. 不要删除当前已有效生成的 `AGENTS.md`、`COMMANDS.md`、`workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/`、`prd/`、`scripts/`、`tests/`、`docs/`。
7. 如发现引用不一致，以当前最终定位为准进行修正。

## 三、重点检查项

### 1. Runtime 误创建检查

检查仓库是否存在以下内容：

- `agentic_qa/`
- `src/agentic_qa/`
- `BaseAgent`
- `BaseTool`
- `WorkflowEngine`
- `LLMProvider`
- `LangGraph`
- `LangChain`
- `LiteLLM`
- 自研 Agent Runtime
- 自研 WorkflowEngine
- 自研 LLM Provider

如果存在，并且不是必要脚本工具，直接移除。

如果只是脚本辅助能力，应迁移到 `scripts/`，不要保留 Python 包式 Runtime 结构。

### 2. 正式目录对齐

确保正式目录存在且职责清晰：

```text
AGENTS.md
COMMANDS.md
workflows/
agents/
tasks/
prompts/
rules/
skills/
knowledge/
prd/
scripts/
tests/
docs/
.github/
pyproject.toml
pytest.ini
```

### 3. 临时任务目录对齐

检查 `_codex_tasks/000-task-index.md`：

- 当前只应列出已经存在的任务文件。
- 不要提前列不存在的任务。
- 明确 `_codex_tasks/` 是临时目录，项目结束后可删除。
- 明确项目正式 `README.md` 在仓库根目录，不在 `_codex_tasks/`。

### 4. QA 报告文件名统一

统一说明并修正引用：

- AI 生成的报告草稿统一命名为：`qa-report-draft.md`
- 路径为：`prd/<id>/80-reports/qa-report-draft.md`
- 人工确认后的正式报告可以命名为：`qa-report.md`

检查并修复以下目录中的混用问题：

- `README.md`
- `COMMANDS.md`
- `AGENTS.md`
- `workflows/`
- `agents/`
- `tasks/`
- `prompts/`
- `rules/`
- `knowledge/`
- `prd/_templates/`
- `scripts/`
- `docs/`

### 5. 路由链路一致性检查

检查每个自然语言命令是否能完整路由到对应文件链路。

至少检查以下链路：

#### 需求分析

```text
COMMANDS.md
-> workflows/01-requirement-analysis-workflow.md
-> tasks/01-analyze-requirement.md
-> agents/requirement-analysis-agent.md
-> prompts/requirement-analysis-prompt.md
-> rules/requirement-analysis-rules.md
-> skills/requirement-decomposition-skill.md
-> skills/business-rule-extraction-skill.md
-> prd/<id>/10-analysis/requirement-analysis.md
```

#### 测试用例生成

```text
COMMANDS.md
-> workflows/02-testcase-generation-workflow.md
-> tasks/02-generate-testcases.md
-> agents/testcase-design-agent.md
-> prompts/testcase-design-prompt.md
-> rules/testcase-rules.md
-> skills/test-design-skill.md
-> knowledge/templates/testcase-template.md
-> prd/<id>/20-testcases/testcases.md
```

#### API 测试脚本生成

```text
COMMANDS.md
-> workflows/03-api-test-generation-workflow.md
-> tasks/03-generate-api-tests.md
-> agents/api-test-generation-agent.md
-> prompts/api-test-generation-prompt.md
-> rules/api-test-rules.md
-> skills/api-contract-analysis-skill.md
-> skills/pytest-api-test-skill.md
-> prd/<id>/30-api-tests/generated/
```

#### UI 测试脚本生成

```text
COMMANDS.md
-> workflows/04-ui-test-generation-workflow.md
-> tasks/04-generate-ui-tests.md
-> agents/ui-test-generation-agent.md
-> prompts/ui-test-generation-prompt.md
-> rules/ui-test-rules.md
-> skills/playwright-ui-test-skill.md
-> prd/<id>/40-ui-tests/generated/
```

#### 执行测试

```text
COMMANDS.md
-> workflows/05-test-execution-workflow.md
-> tasks/05-execute-tests.md
-> agents/test-execution-agent.md
-> prompts/test-execution-prompt.md
-> rules/test-execution-rules.md
-> scripts/run_pytest.py
-> scripts/collect_test_results.py
-> prd/<id>/50-execution-results/
```

#### 失败分析

```text
COMMANDS.md
-> workflows/06-failure-analysis-workflow.md
-> tasks/06-analyze-failures.md
-> agents/failure-analysis-agent.md
-> prompts/failure-analysis-prompt.md
-> rules/failure-analysis-rules.md
-> skills/failure-log-analysis-skill.md
-> prd/<id>/60-failure-analysis/failure-analysis.md
```

#### Bug 草稿

```text
COMMANDS.md
-> workflows/07-bug-draft-workflow.md
-> tasks/07-generate-bug-draft.md
-> agents/bug-draft-agent.md
-> prompts/bug-draft-prompt.md
-> skills/bug-report-writing-skill.md
-> prd/<id>/70-bugs/
```

#### QA 报告

```text
COMMANDS.md
-> workflows/08-report-generation-workflow.md
-> tasks/08-generate-report.md
-> agents/report-generation-agent.md
-> prompts/report-generation-prompt.md
-> skills/qa-report-writing-skill.md
-> knowledge/templates/qa-report-template.md
-> prd/<id>/80-reports/qa-report-draft.md
```

#### 归档

```text
COMMANDS.md
-> workflows/09-archive-workflow.md
-> tasks/09-archive-requirement.md
-> agents/archive-agent.md
-> prompts/archive-prompt.md
-> rules/archive-rules.md
-> scripts/archive_requirement.py
-> prd/<id>/90-archive/archive-index.md
```

### 6. PRD 示例工作区一致性

检查 `prd/sample-login-requirement/`：

- `requirement.md` 存在。
- `api-doc.md` 存在。
- `metadata.yml` 存在。
- 标准目录完整。
- metadata 中 artifacts 路径和 `rules/artifact-path-rules.md` 一致。
- review_gates 状态合法。

### 7. 脚本一致性检查

检查以下脚本是否符合当前结构：

- `scripts/create_prd_workspace.py`
- `scripts/validate_prd_workspace.py`
- `scripts/run_pytest.py`
- `scripts/collect_test_results.py`
- `scripts/generate_markdown_report.py`
- `scripts/archive_requirement.py`

要求：

- 不依赖 `agentic_qa` 包。
- 不依赖未声明模块。
- 能通过 `python scripts/xxx.py` 直接执行。
- 生成路径与 `rules/artifact-path-rules.md` 一致。

### 8. 工程配置一致性检查

检查：

- `pyproject.toml`
- `pytest.ini`
- `.pre-commit-config.yaml`
- `.github/workflows/qa-check.yml`

要求：

- 不声明不存在的 Python 包。
- 不引用 `src/agentic_qa`。
- `pip install -e .` 可执行。
- `pytest` 可执行。
- `ruff check .` 可执行。

## 四、验收命令

完成修复后，执行：

```bash
pip install -e .
python scripts/validate_prd_workspace.py prd/sample-login-requirement
python scripts/create_prd_workspace.py demo-alignment-check
python scripts/validate_prd_workspace.py prd/demo-alignment-check
python scripts/generate_markdown_report.py prd/sample-login-requirement
python scripts/run_pytest.py
pytest
ruff check .
```

如生成了 `prd/demo-alignment-check/`，可以保留作为临时验收工作区，也可以在说明中标注它是校验产生的目录。

## 五、提交要求

直接提交到 `master`。

Commit message：

```text
fix: align command-routed workspace files
```

## 六、完成后的回复要求

完成后请回复：

1. 修复了哪些目录或文件引用不一致。
2. 是否发现并移除了 `agentic_qa` / Runtime / LLM Provider 相关结构。
3. QA 报告路径是否已统一为 `qa-report-draft.md` 草稿 + `qa-report.md` 正式版。
4. 各命令路由链路是否完整。
5. 验收命令是否全部通过。
6. 如果有未完成项，明确列出原因和后续建议。
