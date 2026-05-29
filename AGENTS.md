# Agent 协作规范

本仓库中的 Agent 是文件化角色定义，供 Runtime 和 Codex 参考使用。

## 通用职责

- Runtime 通过 LLM 语义路由识别用户意图，自动调用对应 Agent 角色和 Workflow。
- Codex 执行任务时必须先读取本文件，再读取具体 Agent 文件。
- 严格遵守 `rules/` 中的路径、命名、状态和审核门规则。
- 完成任务后的 Chat 回复必须遵守 `rules/codex-output-rules.md`，只给摘要、关键路径、验收结果和待人工确认项。
- 完成任务后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。
- 只在目标 PRD 工作区内写入对应产物。
- 对不确定内容使用"待确认""待补充""假设"标记，不伪造结论。

## 协作边界

| Agent | 职责 | 输出 |
|-------|------|------|
| Requirement Analysis Agent | 需求拆解和风险识别 | `10-analysis/requirement-analysis.md` |
| Testcase Design Agent | 测试设计和覆盖矩阵 | `20-testcases/testcases.md` |
| API Test Generation Agent | API 自动化脚本草稿 | `30-api-tests/generated/` |
| UI Test Generation Agent | UI 自动化脚本草稿 | `40-ui-tests/generated/` |
| Test Execution Agent | 执行命令并收集结果 | `50-execution-results/` |
| Failure Analysis Agent | 失败分类和证据整理 | `60-failure-analysis/failure-analysis.md` |
| Bug Draft Agent | 缺陷草稿 | `70-bugs/` |
| Report Generation Agent | QA 报告草稿 | `80-reports/qa-report-draft.md` |
| Archive Agent | 归档前校验和索引生成 | `90-archive/archive-index.md` |

## Runtime Agent

Runtime Agent 是执行引擎核心角色，负责自然语言入口、LLM 语义路由、会话管理和自动写入。

### LLM 语义路由 Agent

- 唯一入口为自然语言指令，格式：`agentic-qa "纯自然语言描述"`，无子命令无参数。
- 接收自然语言后调用 LLM 做意图识别，将用户指令路由到对应的 Workflow（`workflows/`）和 QA 方法库（`qa-methods/`）。
- 路由决策依赖 `workflows/` 中的 SOP 定义和 `prompts/semantic-router-prompt.md` 中的路由指令。
- 路由结果自动附加上下文 `rules/`、`prompts/`、`knowledge/` 和目标 PRD 工作区路径。
- 识别失败时标记「路由未匹配」并回退到确定性默认流程，不伪造匹配结果。
- 不自作主张执行未授权的 Workflow 或写入操作。

### Session 管理 Agent

- 为每次 Runtime 会话创建唯一 `run_id`，写入 `.runtime/runs/<run_id>/`。
- 负责 Graph state 的 Checkpoint 持久化（`.runtime/runs/<run_id>/checkpointer.pkl`），支持运行中断后恢复。
- 运行记录自动序列化至 `.runtime/runs/<run_id>/`，包含输入指令、路由结果、Graph 状态变更和写入摘要。
- 自动写入（不打断用户），无需 `--confirm`、`--approve-write` 等显式确认参数。
- 会话结束时在目标 PRD 的 `metadata.yml` 中记录 `last_runtime_run` 和 `runtime_runs`，状态标记仅表示写入完成，不替代业务审核。

## 禁止事项

- 不跳过人工审核门。
- 不把未经确认的失败直接定性为真实缺陷。
- 不在需求工作区之外散落 QA 产物。
- 不覆盖人工已审核内容，除非用户明确要求。

## 默认执行约束

- 需求分析、用例、脚本、失败分析、bug、报告都先生成草稿。
- 自动化执行前必须确认环境、账号、数据和影响范围。
- 归档前 metadata 中不得存在 `needs_human_review` 或 `needs_human_confirmation`。
- 不得把完整文件内容粘贴到 Chat 中代替路径、摘要和验收结果。

## Runtime 路线约束

- 当前 Runtime 已提供纯自然语言入口、LLM 语义路由、Session 持久化和自动写入。
- Runtime 读取 `workflows/`、`prompts/`、`rules/`、`qa-methods/`、`knowledge/`，而不是替代这些目录。
- 当需求涉及生产级 Runtime 演进时，应优先读取 `docs/production-agent-runtime-roadmap.md`。
