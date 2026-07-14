# Agentic-QA 路线图

路线图只区分“当前已验证”和“下一阶段”，未进入当前 WorkflowSpec 的能力不得出现在支持意图中。

## 当前已验证

- YAML WorkflowSpec 驱动 LangGraph，Python 不维护第二套流程。
- 需求分析、测试用例和联合生成。
- API 测试草稿与 `agentic-qa.api-cases.v1.1`。
- RAG API 自动化用例、检索 trace 和 run record。
- UI 自动化草稿、接口发现报告、QA 报告。
- run 候选区、结构化 sidecar、需求级 latest/index。
- Review Gate interrupt、自然语言审核、确定性 promote。
- checkpoint、恢复、重试、质量门、文档一致性检查。
- 零基础设施默认配置；FAISS 和 PostgreSQL 按需启用。

## 下一阶段

1. 为修订意图建立独立 WorkflowSpec，确保新 run 与差异记录完整。
2. 增加真实测试执行 WorkflowSpec，并定义可验证的执行证据 Schema。
3. 在执行证据之上实现失败归因和缺陷草稿，禁止无证据结论。
4. 完善正式产物历史索引、清理策略和 RAG 知识准入。
5. 增加端到端真实 LLM + RAG 契约测试和可观测性基线。

每项能力只有在 WorkflowSpec、Schema、文档和测试同时落地后，才能从“下一阶段”移入“当前已验证”。
