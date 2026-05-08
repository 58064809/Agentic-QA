# 任务 001：初始化最终版 Agentic-QA 工作区

## 任务目标

直接在当前仓库 `58064809/Agentic-QA` 的 `master` 分支上，初始化最终形态的 **Command-routed Human-in-the-loop Agentic QA Workspace**。

中文定位：**指令路由型人机协同 Agentic QA 工作空间**。

核心工作模式：

```text
AI 生成 -> 人审核 -> AI 执行 -> 人确认 -> AI 归档
```

本项目由 Codex / ChatGPT / IDE Agent 提供 AI 执行能力，仓库负责提供：

- Command Routing
- 声明式 Workflow
- Agent Specs
- Task SOP
- Prompts
- Rules
- Skills
- Knowledge
- PRD Workspace
- 测试执行脚本
- 归档规范

## 硬性要求

1. 直接在 `master` 分支开发，不要创建新分支。
2. 文档尽量使用中文。
3. 尽量不自研，优先使用成熟工具和文件化规范。
4. 不要实现 LangGraph、LangChain、LiteLLM、LLM Provider、Web 平台、数据库、向量库、自研 Agent Runtime、自研 WorkflowEngine。
5. 不要删除已有文件；如存在同名文件，先阅读再合并更新。
6. 本任务步子可以大一些，目标是尽快形成可用骨架。

## 需要创建的核心结构

```text
Agentic-QA/
├── README.md
├── AGENTS.md
├── COMMANDS.md
├── pyproject.toml
├── pytest.ini
├── .gitignore
├── .pre-commit-config.yaml
├── .github/
│   ├── pull_request_template.md
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── qa_task.md
│   └── workflows/
│       └── qa-check.yml
├── workflows/
├── agents/
├── tasks/
├── prompts/
├── rules/
├── skills/
├── knowledge/
├── prd/
├── scripts/
├── tests/
└── docs/
```

## workflows 目录

创建以下声明式工作流文件：

- `workflows/01-requirement-analysis-workflow.md`
- `workflows/02-testcase-generation-workflow.md`
- `workflows/03-api-test-generation-workflow.md`
- `workflows/04-ui-test-generation-workflow.md`
- `workflows/05-test-execution-workflow.md`
- `workflows/06-failure-analysis-workflow.md`
- `workflows/07-bug-draft-workflow.md`
- `workflows/08-report-generation-workflow.md`
- `workflows/09-archive-workflow.md`

每个 workflow 必须包含：适用场景、触发命令、主 Agent、辅助 Agent、必须读取的 task/prompt/rules/skills/knowledge、输入文件、输出路径、执行步骤、禁止事项、验收标准、人工审核点。

## agents 目录

创建以下 Agent 角色定义：

- `agents/requirement-analysis-agent.md`
- `agents/testcase-design-agent.md`
- `agents/api-test-generation-agent.md`
- `agents/ui-test-generation-agent.md`
- `agents/test-execution-agent.md`
- `agents/failure-analysis-agent.md`
- `agents/bug-draft-agent.md`
- `agents/report-generation-agent.md`
- `agents/archive-agent.md`

每个 Agent 文件必须包含：Agent 角色、职责边界、输入、输出、必须读取的资料、必须遵守的规则、禁止事项、质量标准、人工审核点。

## tasks 目录

创建以下 SOP：

- `tasks/00-locate-requirement.md`
- `tasks/01-analyze-requirement.md`
- `tasks/02-generate-testcases.md`
- `tasks/03-generate-api-tests.md`
- `tasks/04-generate-ui-tests.md`
- `tasks/05-execute-tests.md`
- `tasks/06-analyze-failures.md`
- `tasks/07-generate-bug-draft.md`
- `tasks/08-generate-report.md`
- `tasks/09-archive-requirement.md`

每个任务文件必须包含：任务目标、触发命令示例、输入文件、必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge、执行步骤、输出路径、禁止事项、验收标准、人工审核点。

## prompts 目录

创建以下 Prompt 模板：

- `prompts/requirement-analysis-prompt.md`
- `prompts/testcase-design-prompt.md`
- `prompts/api-test-generation-prompt.md`
- `prompts/ui-test-generation-prompt.md`
- `prompts/test-execution-prompt.md`
- `prompts/failure-analysis-prompt.md`
- `prompts/bug-draft-prompt.md`
- `prompts/report-generation-prompt.md`
- `prompts/archive-prompt.md`

每个 Prompt 必须包含：角色、任务、输入、输出格式、质量要求、禁止事项、待人工确认项。

## rules 目录

创建以下规则文件：

- `rules/artifact-path-rules.md`
- `rules/naming-rules.md`
- `rules/review-gate-rules.md`
- `rules/status-rules.md`
- `rules/requirement-analysis-rules.md`
- `rules/testcase-rules.md`
- `rules/api-test-rules.md`
- `rules/ui-test-rules.md`
- `rules/automation-rules.md`
- `rules/test-execution-rules.md`
- `rules/failure-analysis-rules.md`
- `rules/archive-rules.md`

重点要求：

- `artifact-path-rules.md` 必须定义所有产物路径。
- `status-rules.md` 必须定义状态：draft、needs_human_review、approved、needs_changes、rejected、needs_human_confirmation、confirmed、archived。
- `failure-analysis-rules.md` 必须定义失败分类：真实缺陷、脚本问题、环境问题、测试数据问题、需求不清、预期错误、接口文档不一致、偶现问题、暂无法判断。

## skills 目录

创建以下 Skills：

- `skills/requirement-decomposition-skill.md`
- `skills/business-rule-extraction-skill.md`
- `skills/test-design-skill.md`
- `skills/equivalence-partitioning-skill.md`
- `skills/boundary-value-analysis-skill.md`
- `skills/scenario-modeling-skill.md`
- `skills/state-transition-modeling-skill.md`
- `skills/risk-based-testing-skill.md`
- `skills/api-contract-analysis-skill.md`
- `skills/pytest-api-test-skill.md`
- `skills/playwright-ui-test-skill.md`
- `skills/failure-log-analysis-skill.md`
- `skills/bug-report-writing-skill.md`
- `skills/qa-report-writing-skill.md`

这些是给 Codex 参考的专业能力说明书，不是代码插件。必须写真实内容，不要空文件。

## knowledge 目录

创建：

```text
knowledge/
├── qa-methodology/
│   ├── equivalence-partitioning.md
│   ├── boundary-value-analysis.md
│   ├── scenario-testing.md
│   ├── state-transition-testing.md
│   └── risk-based-testing.md
├── templates/
│   ├── requirement-analysis-template.md
│   ├── testcase-template.md
│   ├── bug-template.md
│   └── qa-report-template.md
├── project-rules/
│   ├── testcase-writing-rules.md
│   ├── assertion-rules.md
│   ├── automation-coding-rules.md
│   └── review-rules.md
└── historical-lessons/
    └── README.md
```

测试用例模板必须使用：

```markdown
| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
```

## PRD 工作区

创建：

```text
prd/
├── _templates/
├── _registry.yml
└── sample-login-requirement/
    ├── requirement.md
    ├── api-doc.md
    ├── metadata.yml
    ├── 10-analysis/
    ├── 20-testcases/
    ├── 30-api-tests/generated/
    ├── 40-ui-tests/generated/
    ├── 50-execution-results/
    ├── 60-failure-analysis/
    ├── 70-bugs/
    ├── 80-reports/
    └── 90-archive/
```

`prd/sample-login-requirement/requirement.md` 写通用登录需求：手机号密码登录、密码错误提示、连续输错 5 次锁定 15 分钟、登录成功返回 token、token 过期需重新登录。

`api-doc.md` 写对应接口文档示例。

`metadata.yml` 写完整元数据，包含 requirement_id、title、status、owner、created_by、last_updated_by、artifacts、review_gates。

## scripts 目录

实现以下脚本：

- `scripts/create_prd_workspace.py`：创建新需求工作区。
- `scripts/validate_prd_workspace.py`：校验 PRD 工作区结构。
- `scripts/run_pytest.py`：封装 pytest 执行。
- `scripts/collect_test_results.py`：收集测试结果。
- `scripts/generate_markdown_report.py`：生成 Markdown 报告草稿。
- `scripts/archive_requirement.py`：检查审核状态后生成归档索引；若存在 needs_human_review 或 needs_human_confirmation，不允许归档。

## 工程配置

`pyproject.toml` 至少包含：pytest、pytest-json-report、typer、rich、pyyaml、ruff。

`pytest.ini` 配置基础 pytest 参数。

`.pre-commit-config.yaml` 配置 ruff。

`.github/workflows/qa-check.yml` 至少执行：

```bash
pip install -e .
ruff check .
pytest
python scripts/validate_prd_workspace.py prd/sample-login-requirement
```

## 测试要求

创建 `tests/unit/test_workspace_scripts.py`，至少覆盖：

1. create_prd_workspace 可以创建标准目录。
2. validate_prd_workspace 可以校验标准目录。
3. generate_markdown_report 可以生成报告草稿。
4. archive_requirement 在存在未审核状态时拒绝归档。

## 验收命令

完成后必须保证以下命令可执行：

```bash
pip install -e .
python scripts/create_prd_workspace.py demo-requirement
python scripts/validate_prd_workspace.py prd/demo-requirement
python scripts/run_pytest.py
python scripts/generate_markdown_report.py prd/sample-login-requirement
pytest
ruff check .
```

## 提交要求

直接提交到 `master`。

Commit message：

```text
feat: bootstrap command-routed agentic qa workspace
```

## 完成后的回复要求

完成后请回复：

1. 本次新增/修改了哪些核心文件。
2. 如何使用自然语言命令驱动 Codex。
3. 如何新增一个 PRD 需求工作区。
4. 如何执行验收命令。
5. 哪些内容需要我人工审核。
6. 如果有未完成项，明确列出来。
