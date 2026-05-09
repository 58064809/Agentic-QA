# Agent 协作规范

本仓库中的 Agent 是文件化角色定义，不是运行时服务。Codex 执行任务时必须先读取本文件，再读取具体 Agent 文件。

## 通用职责

- 按 `COMMANDS.md` 识别用户自然语言命令。
- 按 `workflows/` 和 `tasks/` 读取必要上下文。
- 严格遵守 `rules/` 中的路径、命名、状态和审核门规则。
- 完成任务后的 Chat 回复必须遵守 `rules/codex-output-rules.md`，只给摘要、关键路径、验收结果和待人工确认项。
- 完成任务后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复，不得只回复“已完成”“已修改”等不可审核短句。
- 只在目标 PRD 工作区内写入对应产物。
- 对不确定内容使用“待确认”“待补充”“假设”标记，不伪造结论。

## 协作边界

- Requirement Analysis Agent 负责需求拆解和风险识别。
- Testcase Design Agent 负责测试设计和覆盖矩阵。
- API/UI Test Generation Agent 负责生成自动化脚本草稿。
- Test Execution Agent 负责执行命令并收集结果。
- Failure Analysis Agent 负责失败分类和证据整理。
- Bug Draft Agent 负责缺陷草稿。
- Report Generation Agent 负责 QA 报告草稿。
- Archive Agent 负责归档前校验和索引生成。

## 禁止事项

- 不实现新的 Agent Runtime、工作流引擎、LLM Provider 或平台服务。
- 不跳过人工审核门。
- 不把未经确认的失败直接定性为真实缺陷。
- 不在需求工作区之外散落 QA 产物。
- 不覆盖人工已审核内容，除非用户明确要求。

## 默认执行约束

- 需求分析、用例、脚本、失败分析、bug、报告都先生成草稿。
- 自动化执行前必须确认环境、账号、数据和影响范围。
- 归档前 metadata 中不得存在 `needs_human_review` 或 `needs_human_confirmation`。
- 不得把完整文件内容粘贴到 Chat 中代替路径、摘要和验收结果。

## 生产级 Runtime 路线约束

- 当前默认执行模式仍然是 Codex 驱动的标准化工作台。
- 当用户要求“生产级 Agent”“LangGraph Runtime”或“Runtime 驱动”时，Codex 应优先读取 `docs/architecture/production-agent-runtime-roadmap.md`。
- Codex 不得把 LangGraph Runtime 和现有声明式工作台对立起来。
- Codex 不得把 Prompt、Rules、Skills 全部硬编码进 Python。
- 后续实现 Runtime 时，应让 Runtime 读取 `workflows/`、`prompts/`、`rules/`、`skills/`、`knowledge/`，而不是替代这些目录。
- Codex 修改 Runtime 前，必须明确当前任务属于第 1 阶段文档工作台，还是第 2 阶段 Runtime 能力。
