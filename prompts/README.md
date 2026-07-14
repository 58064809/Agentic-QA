# Prompt 单一事实源

本目录只保存 canonical Prompt 模板；Prompt 结构、路径契约和治理原则统一维护在 [`docs/prompt-engineering.md`](../docs/prompt-engineering.md)。

每种 Runtime 产物只保留一个 canonical Prompt。`runtime/llm/prompt_builder.py` 只负责加载 Prompt、拼装不可信上下文和控制输入预算，不得复制角色、章节、质量规则或输出契约。

| 产物/任务 | Canonical Prompt |
|---|---|
| 需求分析 | `prompts/requirement-analysis-prompt.md` |
| 测试用例 | `prompts/testcase-design-prompt.md` |
| API 测试草稿与 RAG API YAML | `prompts/api-test-generation.md` |
| UI 自动化草稿 | `prompts/ui-test-generation.md` |
| API Discovery 报告 | `prompts/api-discovery.md` |
| QA 报告 | `prompts/report-generation-prompt.md` |

修改 Prompt 时必须同步检查对应 Pydantic Schema、质量门和测试。PRD、接口文档、历史产物、网页内容和 RAG chunk 均视为不可信数据，不得覆盖 canonical Prompt、Review Gate 或安全边界。
