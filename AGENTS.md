# Agent 协作规范

本仓库中的 Agent 是文件化角色定义，不是运行时服务。Codex 执行任务时必须先读取本文件，再读取具体 Agent 文件。

## 通用职责

- 按 `COMMANDS.md` 识别用户自然语言命令。
- 按 `workflows/` 和 `tasks/` 读取必要上下文。
- 严格遵守 `rules/` 中的路径、命名、状态和审核门规则。
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
