# Agentic-QA

**Agentic-QA** 是一个面向测试工程师的 **Agentic QA Engineering** 项目，用于构建 AI 辅助的软件测试工程工作流。

项目通过自然语言入口、Runtime 编排、配置层管理、RAG 上下文检索、专业 QA Agent、测试方法论、规则约束和确认机制，帮助测试工程师将需求文档转化为结构化的需求分析、测试用例、自动化脚本草稿、执行记录、失败分析、Bug 草稿、QA 报告和可复用知识资产。

## 核心能力

- **统一自然语言入口**：AI Chat、Bot、CLI 和 API 都只是入口形态，Runtime 统一负责意图识别、工作流选择和任务执行。
- **配置层管理**：统一管理 Runtime、RAG、LLM、工作区、协作入口、日志和运行 Profile。
- **Runtime 编排**：负责任务执行、节点流转、状态管理、质量检查、确认门禁和产物写入。
- **运行可靠性策略**：支持节点失败处理、重试、降级、部分产物保留、原子写入、幂等执行和恢复。
- **产物版本管理**：正式产物保持稳定路径，修订结果先生成候选版本，确认后再提升为当前版本，历史版本可追溯。
- **RAG 上下文检索**：当前采用"确定性上下文加载 + 知识库向量检索"的混合模式。
- **自然语言确认机制**：用户可通过 Chat、Bot 或 CLI 表达通过、修改、驳回、继续执行等确认意图。

## Review Gate 原则

> Review Gate 遵循"LLM 负责理解，程序负责裁决"的边界：LLM 或语义解析器只能把用户自然语言转换为结构化 `ReviewDecision`，不能直接写入 `artifacts/`、不能直接把状态改成 `confirmed`、不能执行 promote。

## 文档导航

使用左侧导航浏览完整设计文档，重点包括：

- **架构与设计**：[系统架构](architecture.md) · [建设路线图](roadmap.md)
- **工作流与运行时**：[Workflow DSL](workflow-dsl.md) · [运行时可靠性](runtime-reliability.md) · [产物版本管理](artifact-versioning.md) · [Review Gate](review-gate.md)
- **QA 产物标准**：[产物标准](artifact-standards.md) · [测试用例标准](testcase-standards.md) · [QA 报告生成](qa-report-generation.md)
- **测试生成**：[接口测试生成](api-test-generation.md) · [UI 测试生成](ui-test-generation.md) · [接口发现](api-discovery.md) · [自动化用例生成](automation-case-generation.md)
- **RAG**：[RAG 设计](rag-design.md) · [RAG 架构](rag-architecture.md) · [RAG 运行记录规范](rag-run-record-spec.md)

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -e .
python scripts/create_prd_workspace.py demo-requirement
agentic-qa "分析 prd/demo-requirement 并生成测试用例"
```

项目愿景：让 AI 参与完整 QA 工程生命周期，从需求理解、测试设计、自动化生成，到执行分析、报告归档和知识复用，逐步沉淀为可运行、可追踪、可扩展的智能测试工程体系。
