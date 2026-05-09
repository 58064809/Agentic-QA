# Agentic-QA

Agentic-QA 是一个**指令路由型人机协同 Agentic QA 工作空间**：用自然语言命令驱动 Codex 执行 QA 作业，用文件化规范约束输入、输出、审核门和归档路径。

Agentic-QA 的终极目标是建设生产级 Agentic QA 系统。生产级不是一开始就自研平台，而是逐步具备可路由命令、声明式 QA 工作流、可复用 Agent 角色、可追踪 PRD 产物、Human-in-the-loop 门禁、可恢复 Runtime、运行记录和真实 QA 工具接入能力。

当前阶段不实现完整 Agent Runtime、LLM Provider、工作流引擎、数据库或 Web 平台，而是用 `COMMANDS.md`、`workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/` 和 `prd/` 固定 Codex / ChatGPT / IDE Agent 的执行行为。下一阶段才在不替代现有声明式资产的前提下，引入轻量 LangGraph Runtime。

核心模式：

```text
AI 生成 -> 人审核 -> AI 执行 -> 人确认 -> AI 归档
```

## 两阶段路线

### 第 1 阶段：Codex 驱动的标准化工作台

第 1 阶段继续把 Agentic-QA 做成标准化 QA 工作台，由 Codex / ChatGPT / IDE Agent 读取仓库规则完成 QA 任务。核心资产仍然是 `AGENTS.md`、`COMMANDS.md`、`workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/`、`prd/`、`scripts/` 和 `tests/`。

### 第 2 阶段：LangGraph Runtime 驱动的轻量执行引擎

第 2 阶段新增轻量 Runtime，用 LangGraph 承接流程、状态、条件路由、循环修正、Human-in-the-loop、持久化和运行记录，用 LangChain 承接模型调用、Prompt 模板、结构化输入输出和工具封装。

核心原则：

```text
外层 LangGraph 固定流程，内层关键生成节点用 Agent，底层文件、执行、状态、权限全部使用确定性代码
```

边界说明：

- Agentic-QA 提供标准化上下文和产物规范。
- LangGraph 提供稳定流程编排。
- LangChain 提供模型、Prompt、结构化输出和工具封装。
- Codex 继续负责代码开发和人工协作施工。
- 不要一开始就重写成 Runtime，必须先保留并复用声明式资产。
- 详细路线见 `docs/architecture/production-agent-runtime-roadmap.md` 和 `docs/roadmap.md`。

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
| `docs/` | 架构、路线图和项目说明 |
| `scripts/` | 工作区创建、校验、测试执行、报告和归档脚本 |
| `tests/` | 脚本单元测试 |

## 报告路径约定

- AI 生成的 QA 报告草稿统一写入 `prd/<id>/80-reports/qa-report-draft.md`。
- `qa-report.md` 只表示人工确认后的正式报告，可在后续人工确认流程中生成。
- 报告草稿采用“摘要 + 产物索引”方式生成，不重复粘贴完整需求分析、完整测试用例或完整执行日志。

## Codex 输出约定

- 为减少浏览器卡顿，Codex 完成任务后只在 Chat 中输出摘要、关键文件路径、验收结果和待人工确认项。
- 大段 Markdown、长报告、完整 diff 和批量产物必须写入仓库文件，通过路径查看。
- 审核时优先打开对应文件路径，不要求 Codex 在 Chat 中重复粘贴完整内容。
- Codex 完成任务后应使用统一完成回执，人工审核时优先看“修改文件”和“验收结果”。
- 未执行的验收命令不能视为通过，必须在回执中写明原因。
- 后续 `_codex_tasks/` 任务文件应尽量短，避免要求在 Chat 中生成超长 Markdown。
- `python scripts/validate_docs_consistency.py` 可用于检查仓库文档结构、规则模板和关键引用是否完整。

## GitHub Actions 校验

GitHub Actions 会在 push 到 `master` 和面向 `master` 的 PR 时自动运行基础校验。当前 `CI` workflow 包含文档一致性检查、sample PRD 工作区校验、pytest wrapper、pytest 和 ruff。

CI 不访问真实业务环境，不连接生产服务，也不依赖 secret。

## 快速开始

```bash
pip install -e .
python scripts/create_prd_workspace.py demo-requirement
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/demo-requirement
python scripts/run_pytest.py
python scripts/generate_markdown_report.py prd/sample-login-requirement
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
pytest
ruff check .
```

## Runtime Skeleton

第 2 阶段 Runtime 目前只是最小骨架，已使用 LangGraph `StateGraph` 编排测试用例生成最小流程，但不接入真实 LLM、不接入 LangChain ChatModel、不连接真实业务环境。默认命令为 dry-run，不写入文件：

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
```

只有显式传入 `--approve-write` 才允许写入 `prd/<id>/20-testcases/testcases.md` 草稿。若目标文件已存在，当前骨架默认拒绝覆盖；写入后的状态仍为 `needs_human_review`，不得继续自动生成 API/UI 脚本或归档。

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
