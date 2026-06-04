# 命名规则

- 需求目录使用小写字母、数字和连字符，例如 `sample-login-requirement`。
- Markdown 文件使用小写字母和连字符。
- Python 测试文件使用 `test_*.py`。
- 缺陷草稿建议使用 `bug-<序号>-<简短标题>.md`。
- AI 生成的报告草稿使用 `qa-review.md`；人工确认后的正式报告使用 `qa-report.md`，可后续生成。
- 内部 QA 主产物保持英文固定命名，例如 `requirement-analysis.md`、`test-cases.md`、`test-plan.md`。
- 对外评审导出文件可以使用中文命名，但必须放入 `prd/<id>/exports/`。
- 中文导出建议使用 `<需求标题>-需求分析.md`、`<需求标题>-测试用例.md`、`<需求标题>-QA评审摘要.md`。
- 评审后重新生成对比版时，使用 `*-v2.md`、`*-v3.md`，或复制新的 PRD 工作区。
- 文档轻量清洗输出使用 `input/requirement.cleaned.md`，不得默认覆盖 `input/requirement.md`。

禁止使用含义不清的名称，例如 `new.md`、`tmp.py`、`final2.md`。

禁止把内部主产物改成中文文件名，例如不得把 `cases/test-cases.md` 改名为 `测试用例.md`；中文命名只用于 `exports/` 下的对外评审副本。
