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

生成中的中间结果先写入 `runs/<run-id>/`，不得直接覆盖正式产物。

```text
runs/<run-id>/partial-output.md
runs/<run-id>/output.md
runs/<run-id>/quality-check.json
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

```text
runs/<run-id>/
├── state.json
├── attempts.json
├── events.jsonl
├── output.md
├── partial-output.md
├── error.json
└── quality-check.json
```

`attempts.json` 用于记录每次重试的节点、原因、耗时、错误和最终状态。
