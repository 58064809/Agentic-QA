# Prompts

本目录只保存当前 Runtime 或语义路由实际使用的唯一 Prompt 正文。Prompt 治理规范统一维护在 [`docs/prompt-engineering.md`](../docs/prompt-engineering.md)。

## 当前文件

| Prompt | 用途 | 绑定位置 |
|---|---|---|
| `semantic-router-prompt.md` | 自然语言意图路由 | Runtime intent router |
| `requirement-analysis-prompt.md` | 需求分析 | `workflows/runtime/requirement-analysis.workflow.yml` |
| `testcase-design-prompt.md` | 测试用例设计 | `workflows/runtime/testcase-generation.workflow.yml` |
| `api-test-generation-prompt.md` | API 测试草稿 | `workflows/runtime/api-test-draft.workflow.yml` |
| `ui-test-generation-prompt.md` | UI 自动化草稿 | `workflows/runtime/ui-test-draft.workflow.yml` |
| `api-discovery.md` | 接口发现报告 | `workflows/runtime/api-discovery-report.workflow.yml` |
| `rag-automation-case-prompt.md` | RAG 自动化用例 | `workflows/runtime/rag-automation-case.workflow.yml` |
| `report-generation-prompt.md` | QA 报告 | `workflows/runtime/qa-report.workflow.yml` |

## 约束

- 一个任务只允许一个 Prompt 正文。
- Runtime context files 必须引用本索引中的当前 Prompt。
- 未接入当前 Workflow 的 Prompt 不保留为“兼容版”“节点版”或“未来版”。
- 新能力必须同时提交 Workflow、节点实现、Prompt、测试和文档索引。
