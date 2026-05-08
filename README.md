# Agentic-QA

Agentic-QA 是一个**指令路由型人机协同 Agentic QA 工作空间**。仓库不实现 Agent Runtime、LLM Provider、工作流引擎、数据库或 Web 平台，而是用文件化规范把 Codex / ChatGPT / IDE Agent 的执行行为固定下来。

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
