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
├── checkpoint-manifest.json
└── checkpointer.pkl
```

`run-summary.*` 用于面向人和脚本查看运行摘要；`run-state.json` 与 `graph-state.json` 保存 Runtime 和图状态；`rag.json` 保存召回 trace；`review-events.jsonl` 保存审核事件；`checkpoint-manifest.json` 记录 checkpointer 类型、存储方式、连接环境变量名和 checkpoint 摘要。本地默认使用 `file` 模式；生产或多实例部署可切换到 `postgres`。

当前 Runtime 使用运行级持久化 checkpointer：

- 每个 run 使用稳定的 `thread_id`。
- `runtime.checkpointer=file` 时，`StateGraph` checkpoint 写入当前 run 的 `checkpointer.pkl`，无需外部服务，适合本地开发和 CI。
- `runtime.checkpointer=postgres` 时，Runtime 使用 `langgraph-checkpoint-postgres` 的 `PostgresSaver`；需先安装 `.[postgres]`，连接串只从 `runtime.checkpoint_postgres_dsn_env` 指定的环境变量读取。
- Review Gate 中断后，Runtime 使用同一 `thread_id` 和 checkpointer，通过 `Command(resume=...)` 恢复。
- 失败后，用户修复输入、权限或临时环境问题后，可用同一 run 执行 retry，Runtime 会复用原 `thread_id` 和 checkpointer 重新进入 `StateGraph`，并更新同一运行记录。

LangGraph 的 store 用于跨 thread 的长期数据；当前 QA 产物流转恢复只依赖 checkpointer 和 run record。长期知识、跨需求记忆和 RAG 索引继续由 `knowledge/`、`rag/` 和运行记录承担，不混入单次 workflow checkpoint。

## 目标态扩展

后续如需把完整运行尝试、节点 attempt、错误、质量检查、prompt/output 等细粒度记录全部沉淀回 PRD 工作区，应作为单独重构处理。此类字段可以作为目标态目录结构设计，但不能描述成当前已完整实现。

## LangSmith Observability

复杂 LangGraph workflow 的 trace、debug、状态转移可视化、evaluate 和 runtime metrics 使用 LangSmith。Runtime 不再自研节点事件流文件；本地 `.runtime/runs/<run-id>/` 只保存恢复、审核、RAG 召回和摘要所需记录。

启用方式：

```yaml
observability:
  provider: langsmith
  enabled: true
  api_key_env: LANGSMITH_API_KEY
  project: agentic-qa
```

```powershell
$env:LANGSMITH_API_KEY="<your-langsmith-api-key>"
```

Runtime 会把 `workflow_id`、`run_id`、`thread_id`、project/env、tags 写入 LangGraph runnable config metadata，实际 trace 和 metrics 由 LangSmith 保存和展示。
