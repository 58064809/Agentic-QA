# Harness v2 架构

Agentic-QA 是单 Python distribution 的模块化单体，依赖方向为：

```text
interfaces -> application -> domain
     |              ^
     v              |
bootstrap -> infrastructure
```

`domain/` 只保存公开领域模型和 Review Gate 的纯规则。`application/` 保存用例、端口、
Source Bundle 输入模型和质量评估模型。`infrastructure/` 实现文件仓储、PostgreSQL、
LangGraph、模型、MCP、RAG、来源摄取以及质量策略。`interfaces/` 提供 Harness 门面和 CLI，
`bootstrap.py` 是唯一组合根。

SourceDocument、SourceBundle、SourceIssue 和 SourceCompleteness 位于
`application/source/`，不属于质量领域。QualityStrategy 和 ArtifactNormalizer 是 application
port；策略注册表、通用策略和 `city-opening-rewards` pack 位于 infrastructure。业务 pack 拆分为
parser、rules、validators、remediation、normalizer 和 strategy，domain/application 不导入具体 pack。

来源在 run 创建时按安全限制摄取一次，生成 `source-bundle.json` 和不可变文本快照。RAG、
workspace.read、Agent prefetch 和质量评估都读取该快照，恢复时不重新读取已经变化的 workspace
source。来源内容始终是不可信上下文，不能改变权限、预算或 Review Gate。

Agent 输出先作为 raw artifact 保留。表示层 Normalizer 只能处理换行、行尾空白、末尾换行和
Markdown 表格分隔行空格；业务内容修改只能成为 advisory remediation patch。质量策略对 raw 和
可选 normalized 版本分别只读校验，结果写入 `quality-report.json`。

每个 artifact 以 assessment key 标识一次逻辑评估。Candidate 已提交时，checkpoint 恢复复用
manifest 和质量报告，不重复执行策略；提交前崩溃可以重算纯策略，但同一 key 只能形成一份可见
Candidate 和一组质量事件。

AST 架构测试禁止 domain/application 导入 LangGraph、psycopg、OpenAI、MCP、基础设施实现或
具体策略。LangGraph 只存在于 workflow adapter。PostgreSQL 是唯一 checkpoint；文件系统只保存
workspace、run 投影、来源快照、Candidate、Review 和 published artifact。
