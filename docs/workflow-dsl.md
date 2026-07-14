# Workflow DSL

Agentic-QA Runtime 只执行 `workflows/runtime/*.workflow.yml`。编号式 Workflow Markdown 已删除，不参与路由、上下文或文档兼容。

## 权威实现

| 责任 | 程序事实源 |
|---|---|
| Workflow Schema | `runtime/workflow/schema.py` |
| YAML 加载 | `runtime/workflow/loader.py` |
| 图构建与路由 | `runtime/workflow/builder.py` |
| condition 注册 | `runtime/workflow/conditions.py` |
| workflow 选择与上下文 | `runtime/workflow/catalog.py` |
| workflow 文件 | `workflows/runtime/*.workflow.yml` |

修改 Workflow 行为时必须修改以上实现或当前 YAML，不得新建解释性 Workflow Markdown 作为第二事实源。

## 最小结构

```yaml
id: testcase_generation
name: 测试用例生成
version: 1

input:
  prd_path: required
  user_input: required

state:
  task_type: testcase_generation

nodes:
  - id: command_router
    type: python
    handler: runtime.graph.nodes.mvp_context_loader.mvp_command_router_node

edges:
  - from: start
    to: command_router
  - from: command_router
    to: end
```

必填字段：

- `id`
- `name`
- `version`
- `nodes`
- `edges`

`version` 必须是大于等于 1 的整数。

## 节点

当前支持的 node type：

- `python`
- `rag`
- `agent`
- `validator`
- `writer`
- `review_gate`
- `tool`
- `subgraph`

除 `subgraph` 外，节点必须提供可动态 import 的 `handler`。`subgraph` 必须提供 `workflow`，引用另一个当前 WorkflowSpec，且不得形成循环依赖。

```yaml
nodes:
  - id: context_pipeline
    type: subgraph
    workflow: rag_automation_context_pipeline
```

节点类型用于表达职责，实际执行仍由当前 handler 或 subgraph 绑定完成。

## 边与条件路由

固定边：

```yaml
- from: start
  to: command_router
```

条件边：

```yaml
- from: testcase_quality
  to: artifact_preview_writer
  condition: no_quality_errors

- from: testcase_quality
  to: end
  condition: default
```

约束：

1. `from` 必须是 `start` 或已声明 node id。
2. `to` 必须是 `end` 或已声明 node id。
3. 同一 source 不得混合固定边和条件边。
4. 同一条件路由 source 必须且只能有一条 `condition: default`。
5. 普通 condition 按 YAML 顺序评估，均不命中时走显式 default。
6. 不存在隐式路由到 `end` 的兼容行为。
7. 重复 node id、重复 edge、未知 condition、未知 handler 或循环 subgraph 必须在构图阶段失败。

## 当前 condition

| condition | 含义 |
|---|---|
| `no_errors` | `errors` 为空 |
| `has_errors` | `errors` 非空 |
| `no_quality_errors` | `errors` 与 `quality_errors` 均为空 |
| `has_quality_errors` | 无运行错误但存在质量错误 |
| `review_approved` | Review Gate 已批准且下一动作允许 promote |
| `review_needs_changes` | Review Gate 要求修订 |
| `review_rejected` | Review Gate 驳回候选 |
| `review_waiting` | 等待人工确认 |
| `task_is_analysis` | 当前任务为需求分析 |
| `task_is_testcase_generation` | 当前任务为测试用例生成 |
| `task_is_analysis_or_mvp` | 当前任务为需求分析或分析加用例 |
| `task_is_mvp` | 当前任务为分析加用例，且满足前置质量条件 |
| `ready_to_write_preview` | 当前状态允许写候选文件 |
| `task_is_api_test_draft` | 当前任务为 API 测试草稿 |
| `task_is_ui_test_draft` | 当前任务为 UI 自动化草稿 |
| `task_is_api_discovery_report` | 当前任务为接口发现报告 |
| `task_is_qa_report` | 当前任务为 QA 报告 |
| `default` | 条件路由显式兜底 |

condition 必须先注册到 `runtime/workflow/conditions.py`，再用于 YAML。

## 当前 Runtime Workflow

| workflow_id | 文件 | task_type |
|---|---|---|
| `analysis_and_testcases` | `workflows/runtime/analysis-and-testcases.workflow.yml` | `mvp_analysis_testcases` |
| `requirement_analysis` | `workflows/runtime/requirement-analysis.workflow.yml` | `analysis` |
| `testcase_generation` | `workflows/runtime/testcase-generation.workflow.yml` | `testcase_generation` |
| `api_test_draft` | `workflows/runtime/api-test-draft.workflow.yml` | `api_test_draft` |
| `rag_automation_case_generation` | `workflows/runtime/rag-automation-case.workflow.yml` | `api_test_draft` |
| `rag_automation_context_pipeline` | `workflows/runtime/rag-automation-context.subgraph.workflow.yml` | 无顶层 task_type |
| `rag_automation_case_generation_core` | `workflows/runtime/rag-automation-case-generation.subgraph.workflow.yml` | 无顶层 task_type |
| `rag_automation_promote_pipeline` | `workflows/runtime/rag-automation-promote.subgraph.workflow.yml` | 无顶层 task_type |
| `ui_test_draft` | `workflows/runtime/ui-test-draft.workflow.yml` | `ui_test_draft` |
| `api_discovery_report` | `workflows/runtime/api-discovery-report.workflow.yml` | `api_discovery_report` |
| `qa_report` | `workflows/runtime/qa-report.workflow.yml` | `qa_report` |

## 候选与 Review Gate 顺序

当前生成型 Workflow 的基本顺序是：

```text
生成
  -> 质量检查
  -> artifact_preview_writer
  -> Review Gate interrupt
  -> approved 后 artifact_promoter
```

候选正文写入 `runs/<run-id>/<artifact>.preview.md`，`artifact-preview.md` 只保存候选索引。Review Gate 不直接写正式产物。

## 失败策略

节点可声明 `failure_policy`：

```yaml
failure_policy:
  on_error: retry
  max_attempts: 2
  retry_backoff_seconds: 2
```

支持的行为由 `runtime/workflow/schema.py` 和 `runtime/workflow/builder.py` 决定。required 节点失败不得静默跳过；失败、重试和降级必须写入运行状态。

## 新增 Workflow

1. 在 `workflows/runtime/` 创建唯一 YAML。
2. 使用已注册 handler、condition 和 state 字段。
3. 在 `runtime/workflow/catalog.py` 注册顶层任务及 context files。
4. 在本文件的当前 Workflow 表中登记。
5. 增加真实 YAML 加载和构图测试。
6. 运行：

```bash
python scripts/validate_docs_consistency.py
pytest tests/unit/test_workflow_builder.py tests/unit/test_workflow_runtime_yaml.py
ruff check .
```

禁止为新 Workflow 同时创建编号式 Markdown 流程副本。
