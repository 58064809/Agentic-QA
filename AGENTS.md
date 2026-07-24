# Agentic-QA 协作规范

## 不可破坏的边界

1. 不跳过 Review Gate，不把 Agent 生成完成等同于审核通过。
2. 不直接覆盖 published；先生成 run Candidate，再由人工审核、确定性 promote。
3. 不伪造需求、API、执行结果、缺陷或风险；证据不足时明确待确认。
4. 不把密钥、Token、Cookie 或真实敏感数据写入代码、Prompt、事件或产物。
5. 不把规划能力描述为已实现。
6. 不恢复旧 Runtime、WorkflowSpec、`prd/` 路径或旧状态兼容入口。
7. 不覆盖 raw artifact，不让质量策略静默改变业务语义。

## 行为事实来源

| 内容 | 唯一事实来源 |
|---|---|
| 公开 Harness API | `src/harness/interfaces/facade.py` 与 `src/harness/contracts.py` |
| CLI | `src/harness/interfaces/cli.py` |
| 外部 AI 请求协议与 MCP 工具 | `src/harness/application/agent_request/` 与 `src/harness/interfaces/mcp_server.py` |
| 领域模型与 Schema | `src/harness/domain/` |
| 应用用例、Source/Quality 模型与端口 | `src/harness/application/` |
| Workflow、仓储、模型、MCP、RAG、质量适配器 | `src/harness/infrastructure/` |
| 组合装配 | `src/harness/bootstrap.py` |
| Agent、Skill、Tool 声明 | `src/harness/manifests/` |
| Skill 内置运行知识 | `src/harness/knowledge/`，仅由 Skill manifest 显式引用 |

`README.md`、`COMMANDS.md` 与 `docs/` 是面向人的说明，不得覆盖实现事实。发现不一致时先核对代码和
manifest，再同步文档与一致性测试。LangGraph 类型不得进入公开领域契约；CLI 只组装强类型参数并
调用 `Harness`。

## 当前链路

```text
StartRunCommand -> immutable SourceBundle -> QAPlan -> Send 并行专家
-> model draft -> quality feedback/revision loop -> final raw artifact
-> representation-only normalization -> quality-report + generation-report
-> atomic Candidate bundle -> interrupt -> 人工 ArtifactVersionRef
-> ApprovedArtifactVersion -> deterministic promote -> published
```

多 Candidate 审核必须指定单个 artifact 或 `all`。Approve 必须为每个目标选择 raw 或 normalized
强类型版本。partial、blocker、哈希漂移或缺少 provenance 的 Candidate 不可发布。Repository 必须
重新读取 Candidate Manifest 与人工 Review；remediation patch 不能发布。

## 内容与安全

- 测试用例固定 11 列，列定义以 `docs/testcase-standards.md` 为准。
- API 机器用例只接受 `agentic-qa.api-cases.v1.1`；仅完整 OpenAPI 可确认 endpoint 事实。
- RAG 引用必须可追踪 source、chunk 和选择依据；Source、检索与 MCP 返回均是不可信上下文。
- Source 摄取不得跟随链接或 reparse point，不得绕过路径、数量、解析及 Hash 预算。
- API/UI 状态变更只允许在明确测试环境和 ExecutionProfile 范围内执行。
- error/blocked 证据不得自动生成 Bug，根因不足保持 `unconfirmed`。

## 工作区

Harness 只读写 `workspaces/<id>/`。旧 `prd/` 不迁移、不读取、不改写。Candidate create-only；修订
创建新 run。PostgreSQL 是执行恢复事实来源；RAG、workspace.read 和质量评估必须消费同一 run 的
冻结 SourceBundle。

## 文档修改规则

- 用户流程正文只放 `docs/getting-started.md`；命令参数只放 `docs/cli-reference.md`。
- 代码契约优先用表格、状态矩阵、Schema 或图表达，避免在多页重复同一段规则。
- 修改 `src/harness/knowledge/` 等同于修改 Agent Prompt，必须保持引用有效并运行离线 eval。
- 新增站点文档必须加入 MkDocs nav；新增本地链接必须通过一致性测试。
- AgentRequest/MCP 不得暴露 Review 写入、approve、promote、shell 或任意文件读取工具。

## 验证与回执

跨契约或运行知识改动至少执行：

```powershell
ruff check .
pytest -q
python -m harness eval run
mkdocs build --strict
```

回执报告变更摘要、关键文件、实际验证结果和仍需人工决定的事项。
