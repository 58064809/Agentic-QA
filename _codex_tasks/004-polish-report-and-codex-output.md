# 任务 004：优化报告生成与 Codex 输出体验

## 任务目标

解决当前 003 后暴露出的两个实际使用问题：

1. `qa-report-draft.md` 目前偏“原文拼接”，内容冗长且有截断痕迹，阅读体验一般。
2. Codex / ChatGPT / GitHub 工具在处理大段 Markdown、长 diff、长响应时容易让浏览器卡住。

本任务目标是让项目更适合实际使用：报告更像 QA 摘要报告，Codex 回复更克制，文件变更更容易审查。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 尽量不自研，不创建 Runtime、LLM Provider、LangGraph、LangChain、LiteLLM、`agentic_qa/` 或 `src/agentic_qa/`。
4. 工程脚本仍只放 `scripts/`。
5. 不要生成大段无意义长文，不要把完整原文重复粘贴进报告。

## 具体任务

### 1. 新增 Codex 输出规则

新增 `rules/codex-output-rules.md`，要求 Codex 在完成任务后：

- 不在 Chat 中粘贴完整大文件。
- 不粘贴完整 diff。
- 只输出变更摘要、关键文件路径、验收结果、待人工确认项。
- 大内容必须写入仓库文件，并在回复中给路径。
- 单次回复尽量控制在可读范围内。
- 若任务会产生大量文件，按模块分组说明。

并在 `AGENTS.md`、`COMMANDS.md` 或相关 workflow/task 中引用该规则。

### 2. 优化 QA 报告生成脚本

修改 `scripts/generate_markdown_report.py`。

要求：

- 不再把需求分析、测试用例、执行报告、失败分析原文大段拼进 `qa-report-draft.md`。
- 改为结构化摘要。
- 报告中只保留关键信息、统计、风险、待确认项和产物链接。
- 明确列出完整产物路径，方便人工跳转查看。
- 避免产生半截内容，例如之前报告中出现的 `tok` 截断问题。
- 保留 `status: needs_human_confirmation` 和 `human_confirmation_required: true`。

建议报告结构：

```markdown
# QA 报告草稿：<需求标题>

## 基本信息
## 产物索引
## 需求分析摘要
## 测试用例摘要
## 自动化与执行摘要
## 失败分析摘要
## 风险与阻塞项
## 待人工确认项
## 结论草稿
```

### 3. 重新生成 sample QA 报告草稿

重新生成：

`prd/sample-login-requirement/80-reports/qa-report-draft.md`

要求：

- 不再大段粘贴完整需求分析和完整测试用例。
- 用摘要 + 路径索引方式呈现。
- 保留“当前报告不得作为正式发布结论”。

### 4. 补充或更新测试

更新 `tests/unit/test_workspace_scripts.py`，至少增加断言：

- 生成的报告包含 `产物索引`。
- 生成的报告包含 `待人工确认项`。
- 生成的报告不会把完整测试用例表大段重复粘贴进去。
- 生成的报告不存在明显截断痕迹。

### 5. 更新使用说明

在 `README.md` 或 `docs/codex-usage-guide.md` 中补充：

- 为减少浏览器卡顿，Codex 回复只给摘要，不贴完整文件。
- 大内容写入仓库文件。
- 审核时通过文件路径查看产物。
- 后续任务文件尽量短，不在 Chat 中生成超长 Markdown。

## 验收命令

执行：

```bash
pip install -e .
python scripts/generate_markdown_report.py prd/sample-login-requirement
python scripts/validate_prd_workspace.py prd/sample-login-requirement
python scripts/run_pytest.py
pytest
ruff check .
```

## 提交要求

直接提交到 `master`。

Commit message：

```text
chore: polish qa report and codex output rules
```

## 完成后的回复要求

完成后只回复摘要，不要粘贴完整文件：

1. 改了哪些文件。
2. 报告生成逻辑如何变短。
3. 是否新增 Codex 输出规则。
4. 验收命令是否通过。
5. 哪些内容需要人工审核。
