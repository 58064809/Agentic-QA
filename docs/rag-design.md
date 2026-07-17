# RAG 设计

RAG 是专家 Agent 的只读 typed tool。每条结果必须记录：

- source 路径或稳定标识；
- chunk id 和 locator；
- 选择依据与 confidence；
- 本次 run 的 query。

检索文本始终包裹为不可信上下文，不能改变系统规则、Agent allowlist、预算或 Review Gate。
新 workspace 来源位于 `workspaces/<id>/sources/`；旧 `prd/` 不参与检索。
