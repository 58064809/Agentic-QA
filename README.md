# Agentic-QA

Agentic-QA 是一个**指令路由型人机协同 Agentic QA 工作空间**：用自然语言命令驱动 Codex 执行 QA 作业，用文件化规范约束输入、输出、审核门和归档路径。

本仓库不实现 Agent Runtime、LLM Provider、工作流引擎、数据库或 Web 平台，而是用 `COMMANDS.md`、`workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/` 和 `prd/` 固定 Codex / ChatGPT / IDE Agent 的执行行为。

核心模式：

```text
AI 生成 -> 人审核 -> AI 执行 -> 人确认 -> AI 归档
```

## 工作方式

1. 人用自然语言命令说明要做的 QA 动作，例如“分析 `prd/sample-login-requirement` 并生成测试用例”。
2. Codex 读取 `COMMANDS.md`，路由到对应 `tasks/`、`workflows/`、`agents/`、`prompts/`、`rules/`、`skills/` 和 `knowledge/`。
3. Codex 只在 PRD 工作区内生成产物，并把状态标记为待审核或待确认。
4. 人审核分析、用例、脚本、结果、缺陷和报告。
5. 全部审核通过后，Codex 执行归档脚本生成归档索引。

这就是“指令路由型”：用户不需要调用某个内置平台或 Runtime，只要描述意图，Codex 就按路由表找到声明式文件链路并生成对应产物。

## 为什么不内置 LLM Provider

- 本项目的核心资产是 QA 作业规范，不是模型网关或 Agent 平台。
- Codex、ChatGPT、IDE Agent 已经提供执行能力，仓库只需要约束“读什么、写哪里、何时停下来等人审”。
- 不内置 Provider 可以避免密钥、计费、模型选择和运行时框架耦合，让仓库保持可迁移。
- 所有脚本仅用于文件工作区创建、校验、测试执行、结果收集、报告草稿和归档检查。

## 目录说明

| 目录 | 用途 |
|---|---|
| `workflows/` | 声明式 QA 工作流 |
| `agents/` | Agent 角色和职责边界 |
| `tasks/` | 可执行 SOP |
| `prompts/` | Prompt 模板 |
| `rules/` | 路径、命名、状态、审核和专项规则 |
| `skills/` | 给 Codex 参考的 QA 专业能力说明 |
| `knowledge/` | 方法论、模板、项目规则和历史经验 |
| `prd/` | 需求工作区和产物目录 |
| `scripts/` | 工作区创建、校验、测试执行、报告和归档脚本 |
| `tests/` | 脚本单元测试 |

## 报告路径约定

- AI 生成的 QA 报告草稿统一写入 `prd/<id>/80-reports/qa-report-draft.md`。
- `qa-report.md` 只表示人工确认后的正式报告，可在后续人工确认流程中生成。

## 快速开始

```bash
pip install -e .
python scripts/create_prd_workspace.py demo-requirement
python scripts/validate_prd_workspace.py prd/demo-requirement
python scripts/run_pytest.py
python scripts/generate_markdown_report.py prd/sample-login-requirement
pytest
ruff check .
```

## 完整示例流程

以 `prd/sample-login-requirement` 为例：

1. “请分析登录需求”会路由到 `workflows/01-requirement-analysis-workflow.md`，输出 `10-analysis/requirement-analysis.md`。
2. “请生成测试用例”会路由到 `workflows/02-testcase-generation-workflow.md`，输出 `20-testcases/testcases.md`。
3. “请生成接口测试脚本”会路由到 `workflows/03-api-test-generation-workflow.md`，输出 `30-api-tests/api-test-plan.md` 和 `30-api-tests/generated/test_login_api.py`。
4. “请执行测试”会路由到 `workflows/05-test-execution-workflow.md`，输出 `50-execution-results/execution-report.md`。
5. “请分析失败”会路由到 `workflows/06-failure-analysis-workflow.md`，输出 `60-failure-analysis/failure-analysis.md`。
6. “请生成 QA 报告”会路由到 `workflows/08-report-generation-workflow.md`，输出 `80-reports/qa-report-draft.md`。
7. “请归档”会路由到 `workflows/09-archive-workflow.md`，仅在审核门通过后生成 `90-archive/archive-index.md`。

示例产物均为 AI 草稿或待人工审核内容，不代表正式 QA 结论。

## 自然语言命令示例

- “定位 `sample-login-requirement`，读取需求、接口文档和 metadata，生成需求分析草稿。”
- “基于已审核的需求分析，为 `sample-login-requirement` 生成测试用例。”
- “根据接口文档和测试用例，生成 pytest API 自动化脚本草稿。”
- “执行 `sample-login-requirement` 的测试并收集结果。”
- “分析失败日志，区分真实缺陷、脚本问题、环境问题和需求不清。”
- “为确认的真实缺陷生成 bug 草稿。”
- “生成 QA 报告草稿，等待人工确认。”
- “确认所有 review gate 后，归档该需求。”

## 人工审核原则

AI 可以生成草稿、执行脚本和整理报告，但以下内容必须由人确认：

- 需求理解和业务规则是否准确。
- 测试用例覆盖是否充分。
- 自动化脚本是否允许连接真实环境或使用真实数据。
- 失败分类和缺陷结论是否成立。
- QA 报告和归档是否可以作为正式记录。

## 临时任务目录

`_codex_tasks/` 是施工任务目录，仅用于驱动 Codex 分阶段建设本仓库。项目正式使用说明以根目录 `README.md`、`COMMANDS.md` 和各规范目录为准；建设完成后，`_codex_tasks/` 可删除或归档。
