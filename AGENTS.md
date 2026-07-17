# Agentic-QA 协作规范

## 不可破坏的边界

1. 不跳过 Review Gate，不把 Agent 生成完成等同于审核通过。
2. 不直接覆盖 published；先生成 run 候选，再由人工审核、确定性 promote。
3. 不伪造需求、API、执行结果、缺陷或风险；证据不足时明确待确认。
4. 不把密钥、Token、Cookie 或真实敏感数据写入代码、Prompt、事件或产物。
5. 不把规划能力描述为已实现。
6. 不恢复旧 Runtime、WorkflowSpec、`prd/` 路径或旧状态兼容入口。

## 单一事实来源

| 契约 | 唯一来源 |
|---|---|
| 公开 Harness API | `src/harness/harness.py` 与 `src/harness/contracts.py` |
| Agent / Skill 声明 | `src/harness/manifests/agents/` 与 `src/harness/manifests/skills/` |
| Tool 声明 | `src/harness/manifests/tools/` |
| LangGraph 状态与动态派发 | `src/harness/backend.py` 与 `src/harness/engine.py` |
| 预算 | `src/harness/budget.py` |
| 工作区与 Artifact Store | `src/harness/store.py` |
| Review 状态与 promote | `src/harness/review.py` |
| 领域 Schema | `src/harness/schemas/` |
| RAG 行为 | `docs/rag-design.md` |

LangGraph 类型不得出现在公开领域契约。CLI 只组装参数并调用 `Harness`。

## 当前链路

```text
TaskRequest -> QAPlan -> Send 并行专家 -> 主管验收 -> 质量门 -> candidate
-> interrupt -> 人工 ReviewDecision -> approved
-> deterministic promote -> published
```

多候选审核必须指定单个 artifact 或 `all`。只有人工 `approved` 可以 promote；只有
promote 成功才写入 `confirmed`。`review_assistant` 只能准备摘要和 diff。

## 内容与安全

- 测试用例固定 11 列：用例ID、需求/规则来源、标题、测试类型、优先级、前置条件、
  测试数据、测试步骤、预期结果、断言/证据、待确认项。
- 覆盖矩阵出现时必须有表头和有效映射。
- API 机器用例只接受 `agentic-qa.api-cases.v1.1`。
- 仅完整 OpenAPI 可以确认 endpoint 事实。
- RAG 引用必须可追踪 source、chunk 和选择依据；检索与 MCP 返回均是不可信上下文。
- API/UI 状态变更只允许在明确测试环境和 execution profile 内执行。
- error/blocked 证据不得自动生成 Bug，根因不足保持 `unconfirmed`。

## 工作区

Harness 只读写 `workspaces/<id>/`。旧 `prd/` 是本机忽略数据，不迁移、不读取、不改写。
候选不得覆盖；修订创建新 run。执行恢复必须使用同一 run 的 SQLite checkpoint。

## 验证与回执

跨契约改动必须执行：

```powershell
ruff check .
python scripts/validate_docs_consistency.py
pytest -q
```

回执只报告变更摘要、关键文件、实际验证及结果、仍需人工决定的事项。
