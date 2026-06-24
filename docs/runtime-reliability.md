# Runtime 可靠性策略

Agentic-QA Runtime 必须保证工作流执行可重试、可恢复、可追踪，并避免失败运行污染正式产物。

## 失败处理

节点失败时由 `failure_policy` 决定后续动作。

| 策略 | 说明 | 常见场景 |
|---|---|---|
| `retry` | 重试当前节点 | LLM 调用失败、RAG 检索失败、外部 API 超时 |
| `skip` | 跳过非关键节点继续执行 | 可选附件解析、非关键补充分析 |
| `fallback` | 进入兜底节点 | RAG 失败后仅使用需求正文，LLM 失败后使用模板 |
| `fail_workflow` | 终止当前工作流 | 需求文件缺失、Schema 校验失败、产物写入失败 |
| `wait_for_user` | 暂停并等待用户补充 | 输入不足、权限不足、需求规则缺失 |
| `compensate` | 执行补偿逻辑 | 已写入部分文件，需要回滚、标记废弃或恢复上个版本 |

节点可以通过 `required` 标记是否为主链路必需节点。

- `required: true`：失败后不得静默跳过。
- `required: false`：可按策略降级、跳过或进入兜底流程。

## 部分成功

生成中的中间结果先进入候选产物或 Runtime 内部运行记录，不得直接覆盖正式产物。

```text
prd/<需求ID>/runs/<run-id>/artifact-preview.md
.runtime/runs/<run-id>/run-summary.md
.runtime/runs/<run-id>/run-state.json
```

如果生成过程中断、只生成部分测试用例或部分分析内容，Runtime 应将运行状态标记为 `partial` 或 `failed`，并保留中间结果供用户查看、修订或重新生成。

部分成功结果不得直接写入：

```text
artifacts/testcases.md
```

只有通过质量检查和写入策略后，产物才允许进入：

```text
artifacts/
```

## 原子写入

正式产物写入采用原子策略。

```text
生成输出
  ↓
写入运行目录
  ↓
质量检查
  ↓
生成 artifact preview
  ↓
确认门禁
  ↓
原子写入 artifacts/
  ↓
创建或更新 reviews/、history/、metadata.yml
```

失败时必须保留上一个可用产物，不允许使用部分结果覆盖正式文件。

## 幂等性

Runtime 使用 `idempotency_key` 识别重复请求。

```text
idempotency_key = hash(prd_path + workflow_id + user_message + input_files_hash + profile)
```

| 场景 | 处理 |
|---|---|
| 相同输入、相同工作流、相同 `idempotency_key` 已成功 | 复用已有运行结果 |
| 相同输入但上次失败 | 允许创建新的 retry attempt |
| 输入文件变化 | 生成新的运行记录 |
| 用户明确要求重新生成 | 新建运行记录，并将旧产物标记为 `superseded` |
| 写入正式产物前失败 | 不改变 `artifacts/` 下的正式产物 |
| 写入正式产物后失败 | 根据运行记录、manifest 或补偿策略恢复一致状态 |

## 运行尝试

同一次用户请求可以包含多个 attempt。

## 当前实现路径

### PRD 工作区运行指针

PRD 工作区下的 `runs/` 当前用于保存候选产物、结构化 preview 伴随文件、latest 指针和需求级运行索引。

```text
prd/<需求ID>/runs/
├── latest.yml
├── index.jsonl
└── <run-id>/
    ├── artifact-preview.md
    ├── artifact-preview.json
    └── artifact-preview.yml
```

### Runtime 内部运行记录

Runtime 内部执行状态、图状态、RAG trace、review events 和恢复数据当前保存在 `.runtime/runs/<run-id>/`。

```text
.runtime/runs/<run-id>/
├── run-summary.json
├── run-summary.md
├── run-state.json
├── graph-state.json
├── review-events.jsonl
├── rag.json
└── checkpointer.pkl
```

`run-summary.*` 用于面向人和脚本查看运行摘要；`run-state.json` 与 `graph-state.json` 保存 Runtime 和图状态；`rag.json` 保存召回 trace；`review-events.jsonl` 保存审核事件；`checkpointer.pkl` 用于恢复 LangGraph checkpointer。

## 目标态扩展

后续如需把完整运行尝试、节点 attempt、错误、质量检查、prompt/output 等细粒度记录全部沉淀回 PRD 工作区，应作为单独重构处理。此类字段可以作为目标态目录结构设计，但不能描述成当前已完整实现。
