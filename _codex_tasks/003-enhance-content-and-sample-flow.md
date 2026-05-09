# 任务 003：补强内容质量并跑通示例 QA 闭环

## 一、任务目标

基于当前已经完成的 `Command-routed Human-in-the-loop Agentic QA Workspace` 骨架，继续补强内容质量，让仓库不只是有目录和文件，而是具备可供 Codex 实际执行的高质量 QA 作业规范。

本任务重点是：

1. 补强 `workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/` 的内容质量。
2. 基于 `prd/sample-login-requirement/` 跑通一个示例 QA 闭环产物。
3. 保持当前技术边界：不自研 Runtime，不接 LLM Provider，不创建 Python Agent 包。
4. 让后续我在 Chat 中说“帮我分析 XXX 需求 / 生成 XXX 用例 / 生成 XXX 接口脚本”时，Codex 能更稳定命中规则和产物路径。

## 二、硬性要求

1. 直接在 `master` 分支修改，不创建新分支。
2. 文档尽量使用中文。
3. 尽量不自研，优先使用成熟工具和文件化规范。
4. 不要创建 `agentic_qa/`、`src/agentic_qa/`、`BaseAgent`、`WorkflowEngine`、`LLM Provider`、`LangGraph`、`LangChain`、`LiteLLM` 等运行时结构。
5. 工程脚本只放 `scripts/`。
6. 不要推翻现有结构，只做内容增强、引用一致性修复和示例闭环产物补齐。
7. 生成的示例产物必须明确标记为 AI 草稿或待人工审核，不得标记为正式结论。

## 三、重点增强范围

### 1. 补强 README.md

增强 README，使其更适合第一次使用者。

至少补充：

- 项目一句话定位。
- 为什么这是指令路由型人机协同 QA 工作空间。
- 为什么不内置 LLM Provider。
- 用户自然语言命令如何路由。
- 一个完整示例：从 sample-login-requirement 到需求分析、用例、接口脚本、执行、失败分析、报告、归档。
- 明确 `_codex_tasks/` 是临时施工任务目录，项目完成后可删除。
- 常用命令清单。
- 人工审核点说明。

### 2. 补强 COMMANDS.md

让 `COMMANDS.md` 更像真正的自然语言路由规范。

至少补充：

- 常见中文触发表达。
- 模糊需求名匹配规则。
- 多个 PRD 候选时不得猜测，应列出候选并等待确认。
- 缺少前置产物时的处理规则。
- 未审核上游产物时的处理规则。
- 每个路由项必须清晰列出：Workflow、Task、Agent、Prompt、Rules、Skills、Knowledge、输入、输出、状态。

### 3. 补强 workflows/

逐个检查并增强 9 个 workflow。

每个 workflow 必须具备：

- 适用场景。
- 触发命令示例。
- 主 Agent。
- 辅助 Agent。
- 必须读取的文件。
- 前置条件。
- 执行步骤。
- 输出路径。
- 状态标记。
- 禁止事项。
- 验收标准。
- 人工审核点。
- 异常处理。

重点增强以下工作流：

- `01-requirement-analysis-workflow.md`
- `02-testcase-generation-workflow.md`
- `03-api-test-generation-workflow.md`
- `05-test-execution-workflow.md`
- `06-failure-analysis-workflow.md`
- `08-report-generation-workflow.md`

### 4. 补强 agents/

逐个增强 Agent 角色定义。

每个 Agent 文件必须回答清楚：

- 这个 Agent 负责什么。
- 不负责什么。
- 输入从哪里来。
- 输出写到哪里。
- 必须读取哪些 workflow/task/prompt/rule/skill/knowledge。
- 哪些情况必须暂停并等待人工确认。
- 输出质量如何判断。

重点增强：

- `requirement-analysis-agent.md`
- `testcase-design-agent.md`
- `api-test-generation-agent.md`
- `test-execution-agent.md`
- `failure-analysis-agent.md`
- `report-generation-agent.md`

### 5. 补强 prompts/

Prompt 要能直接给 Codex 使用，不能只是空泛描述。

每个 Prompt 至少包含：

- 角色设定。
- 任务目标。
- 输入材料。
- 必须参考的规则。
- 输出格式。
- 禁止事项。
- 待人工确认项。

重点要求：

#### requirement-analysis-prompt.md

输出至少包含：

- status
- human_review_required
- 需求摘要
- 业务规则
- 用户流程
- 数据规则
- 权限/状态规则
- 异常场景
- 测试风险
- 待确认问题
- 需求到测试关注点映射

#### testcase-design-prompt.md

必须要求输出 Markdown 表格：

```markdown
| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
```

并要求覆盖：

- 正常流程
- 异常流程
- 边界值
- 状态流转
- 权限/认证
- 数据一致性
- 回归风险

#### api-test-generation-prompt.md

必须要求输出：

- API 测试计划
- 测试数据设计
- 环境变量说明
- pytest 脚本草稿
- 断言策略
- 禁止连接生产环境说明

#### failure-analysis-prompt.md

必须使用固定失败分类：

- 真实缺陷
- 脚本问题
- 环境问题
- 测试数据问题
- 需求不清
- 预期错误
- 接口文档不一致
- 偶现问题
- 暂无法判断

### 6. 补强 rules/

规则必须具备可执行性，不只是原则。

重点增强：

- `review-gate-rules.md`：明确哪些任务必须依赖上游审核。
- `status-rules.md`：明确状态流转和谁有权确认。
- `testcase-rules.md`：明确用例质量门槛。
- `api-test-rules.md`：明确接口自动化生成标准。
- `automation-rules.md`：明确禁止真实凭据、禁止生产环境默认执行。
- `failure-analysis-rules.md`：明确失败分类和证据要求。
- `archive-rules.md`：明确归档前置条件。

### 7. 补强 skills/

Skills 是给 Codex 使用的专业能力说明书，不是代码插件。

重点增强：

- `requirement-decomposition-skill.md`
- `business-rule-extraction-skill.md`
- `test-design-skill.md`
- `equivalence-partitioning-skill.md`
- `boundary-value-analysis-skill.md`
- `scenario-modeling-skill.md`
- `state-transition-modeling-skill.md`
- `risk-based-testing-skill.md`
- `api-contract-analysis-skill.md`
- `pytest-api-test-skill.md`
- `failure-log-analysis-skill.md`

每个 skill 至少包含：

- 适用场景。
- 操作步骤。
- 输入信息。
- 输出要求。
- 常见遗漏点。
- 示例。

### 8. 补强 knowledge/

知识库要从“有文件”变成“有可复用知识”。

重点补强：

- `knowledge/qa-methodology/equivalence-partitioning.md`
- `knowledge/qa-methodology/boundary-value-analysis.md`
- `knowledge/qa-methodology/scenario-testing.md`
- `knowledge/qa-methodology/state-transition-testing.md`
- `knowledge/qa-methodology/risk-based-testing.md`
- `knowledge/templates/requirement-analysis-template.md`
- `knowledge/templates/testcase-template.md`
- `knowledge/templates/bug-template.md`
- `knowledge/templates/qa-report-template.md`
- `knowledge/project-rules/testcase-writing-rules.md`
- `knowledge/project-rules/assertion-rules.md`
- `knowledge/project-rules/automation-coding-rules.md`
- `knowledge/project-rules/review-rules.md`

模板要能直接复制使用。

### 9. 跑通 sample-login-requirement 示例闭环

基于 `prd/sample-login-requirement/`，生成一套示例 QA 产物，全部标记为草稿或待人工审核。

需要生成或补齐：

```text
prd/sample-login-requirement/10-analysis/requirement-analysis.md
prd/sample-login-requirement/20-testcases/testcases.md
prd/sample-login-requirement/30-api-tests/api-test-plan.md
prd/sample-login-requirement/30-api-tests/generated/test_login_api.py
prd/sample-login-requirement/50-execution-results/execution-report.md
prd/sample-login-requirement/60-failure-analysis/failure-analysis.md
prd/sample-login-requirement/80-reports/qa-report-draft.md
```

要求：

- 需求分析必须包含 `status: needs_human_review` 和 `human_review_required: true`。
- 测试用例必须使用固定表格列：标题、优先级、前置条件、测试步骤、预期结果。
- API 测试脚本必须是 pytest 风格草稿，不连接真实生产环境。
- 执行报告可以基于当前本地测试命令生成，不得伪造真实业务接口结果。
- 失败分析如果没有真实失败日志，应明确写“暂无真实失败日志，以下为示例分析框架”。
- QA 报告只能生成 `qa-report-draft.md`。

### 10. 更新 metadata

更新 `prd/sample-login-requirement/metadata.yml`，记录已有示例产物路径。

不要把 review gate 改成已审核，除非有明确人工确认。

## 四、验收命令

执行：

```bash
pip install -e .
python scripts/validate_prd_workspace.py prd/sample-login-requirement
python scripts/generate_markdown_report.py prd/sample-login-requirement
python scripts/run_pytest.py
pytest
ruff check .
```

如果生成了示例 API 测试脚本，但没有真实服务地址，允许通过环境变量或 pytest skip 保护，不能导致默认测试失败。

## 五、提交要求

直接提交到 `master`。

Commit message：

```text
docs: enhance agentic qa content and sample flow
```

## 六、完成后的回复要求

完成后请回复：

1. 增强了哪些文档、规则、Prompt、Skills、Knowledge。
2. sample-login-requirement 生成了哪些示例产物。
3. 是否仍然没有创建 Runtime / LLM Provider / agentic_qa 包。
4. 验收命令是否全部通过。
5. 哪些产物需要我人工审核。
6. 如果有未完成项，明确说明原因。
