# Runtime 可靠性策略

Agentic-QA Runtime 必须保证执行可失败、可恢复、可追踪，并且任何失败或部分成功都不能污染正式产物。

## 可靠性边界

- Workflow 行为由 `workflows/runtime/*.workflow.yml` 与 `runtime/workflow/builder.py` 决定。
- 工作区路径由 `runtime/workspace.py` 决定。
- Review Gate 与 promote 是两个独立阶段。
- 生成内容先写候选正文，再进入人工确认。
- 失败、partial、needs_changes 和 rejected 状态不得写入正式产物。

## 失败策略

节点失败由 `failure_policy` 处理：

| 策略 | 行为 | 适用场景 |
|---|---|---|
| `retry` | 重试当前节点 | LLM、RAG、外部 API 的临时错误 |
| `skip` | 记录 warning 后跳过非关键节点 | 可选附件或补充分析 |
| `fallback` | 进入明确配置的兜底行为 | RAG 失败后只用需求正文 |
| `fail_workflow` | 终止运行 | 必需输入缺失、Schema 或写入失败 |
| `wait_for_user` | interrupt 并等待补充 | 信息、权限或确认不足 |
| `compensate` | 执行明确补偿 | 已发生部分确定性写操作 |

`required: true` 节点失败后不得静默继续。fallback 必须显式配置，不得通过旧链路兼容或隐式路径猜测完成。

## 候选产物

每个 artifact 使用独立候选正文：

```text
prd/<id>/runs/<run-id>/
├── artifact-preview.md
├── artifact-preview.json
├── artifact-preview.yml
├── requirement-analysis.preview.md
├── testcases.preview.md
└── <artifact>.preview.yml/json
```

`artifact-preview.md` 只保存候选索引。具体内容、结构化伴随文件和 `runs/latest.yml.output_paths` 必须指向 `<artifact>.preview.md`。

部分成功可以保留已生成候选和 Runtime 内部记录，但必须标记 `partial` 或 `failed`，不得进入 `artifacts/`。

## 正式写入

```text
生成
  -> 质量检查
  -> 写入 <artifact>.preview.md
  -> 写入候选索引与运行指针
  -> Review Gate interrupt
  -> approved
  -> promote
  -> 归档旧正式版本
  -> 原子写入 artifacts/<artifact>.md
  -> 更新 review、history index、metadata.yml
  -> confirmed
```

正式写入失败时必须保留上一正式版本。不得用不完整候选覆盖正式文件。

## 幂等

推荐幂等键：

```text
hash(prd_path + workflow_id + user_message + input_files_hash + profile)
```

| 场景 | 处理 |
|---|---|
| 相同幂等键已有成功运行 | 复用已有结果 |
| 上次运行失败 | 创建 retry attempt 或按当前 run 恢复 |
| 输入文件变化 | 创建新 run |
| 用户明确重新生成 | 创建新 run，并保留旧候选和正式历史 |
| promote 前失败 | 不改变正式产物 |
| promote 中失败 | 根据原子写入和运行记录恢复一致状态 |

不得通过读取旧目录或旧文件名实现幂等复用。

## PRD 运行指针

```text
prd/<id>/runs/
├── latest.yml
├── index.jsonl
└── <run-id>/
    ├── artifact-preview.md
    ├── artifact-preview.json
    ├── artifact-preview.yml
    ├── <artifact>.preview.md
    ├── <artifact>.preview.json
    └── <artifact>.preview.yml
```

`latest.yml` 至少记录：

- `run_id`
- `thread_id`
- `workflow_id` 或 `task_type`
- `output_paths`
- `preview_index_path`
- `review_status`
- `quality_errors`
- `warnings`

## Runtime 内部运行记录

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

本地文件用于摘要、恢复元数据和调试。目标部署使用 PostgreSQL checkpointer 时，checkpoint 主数据保存在数据库；`checkpoint-manifest.json` 只记录连接配置来源和摘要，不保存密钥。

## Checkpoint 与恢复

- 每个 run 使用稳定 `thread_id`。
- Review Gate 必须通过 LangGraph interrupt 暂停。
- `resume` 使用同一 `thread_id` 和 checkpointer。
- 恢复时不得重新解释为另一套旧 Workflow。
- checkpoint 连接串只从配置指定的环境变量读取。
- checkpoint 不承担跨需求长期知识；长期资产仍由 `knowledge/`、RAG 索引和正式产物管理。

## 可观测性

LangSmith 可用于 Workflow trace、状态转移、延迟、评估和错误定位。Runtime 元数据应包含 `workflow_id`、`run_id`、`thread_id`、project/env 和 tags。

本地运行记录只保存恢复、审核、RAG 和摘要所需内容，不再自建重复的完整事件系统。

## 校验

```bash
python scripts/validate_docs_consistency.py
python scripts/validate_docs_consistency.py --watch
pytest tests/unit/test_workflow_runtime_yaml.py
pytest
ruff check .
```

严格检查必须阻止候选路径漂移、旧 Workflow 引用、重复 Prompt 和 Runtime context 悬空文件进入主分支。
