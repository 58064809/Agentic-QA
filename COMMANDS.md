# 自然语言命令路由

Runtime 通过 LLM 语义路由自动识别用户意图，无需子命令或参数。用户只需输入纯自然语言命令，Runtime 自动路由到对应 Workflow 和 Agent。

所有任务完成后的 Chat 回复必须遵守 `rules/codex-output-rules.md`：不粘贴完整大文件或完整 diff，只输出摘要、关键路径、验收结果和待人工确认项。
完成回执必须包含：变更摘要、修改文件、验收结果、待人工确认、下一步建议。

## LLM 语义路由

Agentic-QA 的入口为纯自然语言命令 `agentic-qa "你的需求"`，无需子命令或参数。Codex 通过 LLM 语义理解将自然语言路由到对应的 Workflow。

### 设计原则

- **纯自然语言入口**：用户只需输入 `agentic-qa "描述你的需求"`，系统自动理解意图。
- **LLM 语义路由**：不依赖关键词匹配，由 LLM 理解用户意图并路由到正确的工作流。
- **Session 持久化**：同一需求的多次交互保持上下文连续，支持增量修订和状态追踪。
- **自动写入**：产物自动写入目标 PRD 工作区，不打断用户等待确认。
- **无子命令无参数**：无 `--flag`、`-o` 等参数记忆负担，一句话完成所有操作。

### 路由流程

```text
用户输入 agentic-qa "自然语言命令"
  → LLM 理解意图，匹配最合适 Workflow
  → Session 管理器创建/恢复对话上下文
  → LangGraph 工作流按意图执行
  → 自动写入产物到 prd/<id>/ 对应目录
  → 进入 REPL 等待下一轮命令
```

### 与传统路由的差异

| 维度 | 传统关键词路由 | LLM 语义路由 |
|------|---------------|-------------|
| 入口 | `agentic-qa "分析登录需求"` | `agentic-qa "分析登录需求"` |
| 参数 | 子命令 + 可选参数 | 纯自然语言，无参数 |
| 匹配方式 | 关键词 + 规则匹配 | LLM 语义理解 |
| 持久化 | 手动或脚本触发 | 自动 Session 持久化 |
| 写入方式 | 需 `--confirm` 确认 | 自动写入，不打断 |

## 路由表

| 用户意图关键词 | Workflow | Agent | Prompt | Rules | Skills/Knowledge | 输入 | 输出 | 状态 |
|---|---|---|---|---|---|---|---|---|
| 分析需求、拆解需求 | `workflows/01-requirement-analysis-workflow.md` | Requirement Analysis Agent | `prompts/requirement-analysis-prompt.md` | `rules/requirement-analysis-rules.md` | `skills/analysis/requirement-decomposition-skill.md`、`skills/analysis/business-rule-extraction-skill.md` | `input/requirement.md`、`input/api.md`、`workspace.yml` | `runs/<run_id>/analysis/requirement-analysis.md` | `needs_human_review` |
| 生成测试用例、设计用例 | `workflows/02-testcase-generation-workflow.md` | Testcase Design Agent | `prompts/testcase-design-prompt.md` | `rules/testcase-rules.md` | `skills/test-design/test-design-skill.md`、`knowledge/templates/testcase-template.md` | 已审核或待审需求分析 | `runs/<run_id>/cases/test-cases.md` | `needs_human_review` |
| Runtime 生成测试用例、自动生成测试 | `workflows/10-runtime-testcase-generation-workflow.md` | Runtime Testcase Generation Node | `prompts/runtime-testcase-generation-prompt.md` | `rules/testcase-rules.md`、`rules/review-gate-rules.md` | `skills/test-design/test-design-skill.md`、`skills/test-design/equivalence-partitioning-skill.md`、`skills/test-design/boundary-value-analysis-skill.md`、`skills/test-design/state-transition-modeling-skill.md` | Runtime 上下文、声明式资产（Workflow/Prompt/Rules/Skills/Knowledge） | `prd/<id>/runs/<run_id>/cases/test-cases.md` | `needs_human_review` |
| 生成 API 测试、接口自动化 | `workflows/03-api-test-generation-workflow.md` | API Test Generation Agent | `prompts/api-test-generation-prompt.md` | `rules/api-test-rules.md` | `skills/automation/api-contract-analysis-skill.md`、`skills/automation/pytest-api-test-skill.md` | 接口文档、测试用例 | `automation/api/test-plan.md`、`automation/api/generated/` | `needs_human_review` |
| 生成 UI 测试、端到端测试 | `workflows/04-ui-test-generation-workflow.md` | UI Test Generation Agent | `prompts/ui-test-generation-prompt.md` | `rules/ui-test-rules.md` | `skills/automation/playwright-ui-test-skill.md` | 需求、用例、页面入口 | `automation/ui/generated/` | `needs_human_review` |
| 执行测试、跑测试 | `workflows/05-test-execution-workflow.md` | Test Execution Agent | `prompts/test-execution-prompt.md` | `rules/test-execution-rules.md` | `scripts/run_pytest.py`、`scripts/collect_test_results.py` | 已审核脚本、执行环境 | `execution/runs/` | `needs_human_review` |
| 分析失败、看日志 | `workflows/06-failure-analysis-workflow.md` | Failure Analysis Agent | `prompts/failure-analysis-prompt.md` | `rules/failure-analysis-rules.md` | `skills/reporting/failure-log-analysis-skill.md` | 执行结果、日志、用例 | `defects/failure-analysis.md` | `needs_human_review` |
| 生成 bug、提缺陷 | `workflows/07-bug-draft-workflow.md` | Bug Draft Agent | `prompts/bug-draft-prompt.md` | `rules/failure-analysis-rules.md` | `skills/reporting/bug-report-writing-skill.md` | 失败分析、证据 | `defects/bug-drafts/` | `needs_human_review` |
| 生成报告、QA 报告 | `workflows/08-report-generation-workflow.md` | Report Generation Agent | `prompts/report-generation-prompt.md` | `rules/status-rules.md` | `skills/reporting/qa-report-writing-skill.md`、`knowledge/templates/qa-report-template.md` | 全部 QA 产物 | `report/qa-review.md` | `needs_human_review` |
| 归档需求、完成归档 | `workflows/09-archive-workflow.md` | Archive Agent | `prompts/archive-prompt.md` | `rules/archive-rules.md` | `scripts/archive_requirement.py` | metadata、正式报告、全部产物 | `archive/index.md` | `archived` |

## 常见中文触发表达

- 需求分析："分析这个需求""拆一下登录需求""帮我看 PRD""提取业务规则"。
- 用例生成："生成测试用例""设计覆盖场景""补边界用例""列回归用例"。
- Runtime 测试生成："运行时生成测试用例""自动生成测试""Runtime 自动用例生成"。
- API 测试："生成接口自动化""写 pytest 草稿""根据接口文档出测试脚本"。
- UI 测试："生成 Playwright 脚本""做端到端测试草稿""覆盖登录页面流程"。
- 测试执行："跑测试""执行自动化""收集 pytest 结果"。
- 失败分析："看失败日志""判断失败原因""分类这些失败"。
- 缺陷草稿："生成 bug 草稿""整理缺陷报告""把真实缺陷写成 issue"。
- QA 报告："生成 QA 报告草稿""汇总测试结果""输出风险结论草稿"。
- 归档："归档这个需求""生成归档索引""确认完成后归档"。
- 评审修订："根据评审意见修订需求分析和用例""按会议结论增量修改""不要重写，保留评审意见"。
- 中文导出："导出中文评审文件""把需求分析和测试用例导出给产品看""生成 QA 评审摘要"。
- 状态标记："标记需求分析已评审""这版通过""确认可以作为后续输入""打回重改"。

## 命令解析规则

- 需求名模糊时，先按 `prd/_registry.yml` 的 `requirement_id`、`title`、`path` 做包含匹配。
- 如果匹配到多个 PRD 候选，不得猜测；必须列出候选路径并等待用户确认。
- 如果没有匹配到 PRD，询问用户是否创建新工作区，或要求提供明确路径。
- 如果缺少前置产物，先生成缺失的上游草稿，或明确说明阻塞项。
- 若目标产物依赖未审核上游产物，必须停止并提示人工审核。
- 若目标产物已存在，先检查状态，再决定覆盖、增量修订或版本化。
- `needs_human_review` 状态允许覆盖草稿，但应说明覆盖原因。
- `needs_revision` 状态允许增量修订，不建议整份重写。
- `reviewed` 状态默认只做增量修订，必须保留评审意见。
- `approved` 状态禁止直接覆盖，只能追加补充或新建 `*-v2.md` 对比版。
- 用户只说"生成出来了"不算人工确认；明确说"这版通过""已评审""确认可以作为后续输入"，或在 metadata/front matter 写入 reviewer 信息，才算已评审或已确认。
- 若命令包含"直接执行""跑测试"，仍需检查执行环境、测试数据和风险。
- 若命令包含"归档"，必须先运行 `scripts/archive_requirement.py` 的审核状态检查。
- AI 生成的 QA 报告只能写入 `prd/<id>/report/qa-review.md`；人工确认后的正式报告可命名为 `qa-report.md`。
- 内部主产物保持英文固定路径；对外评审导出文件可放在 `prd/<id>/exports/` 并使用中文命名。
- 大段产物内容必须写入仓库文件，Chat 中只提供文件路径和摘要。
- 每个任务完成后必须输出标准回执，验收命令必须明确区分"通过 / 失败 / 未执行"。

## 推荐命令格式

```text
请对 prd/sample-login-requirement 执行需求分析，并写入 runs/<run_id>/analysis/requirement-analysis.md，等待我审核。
```

```text
基于已审核用例，为 prd/sample-login-requirement 生成 pytest API 测试草稿。
```

```text
执行 prd/sample-login-requirement 的测试，收集结果并生成 QA 报告草稿。
```
