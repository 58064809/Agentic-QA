# Workflow DSL

本文档定义 Agentic-QA Runtime 使用的最小 Workflow DSL。工作流用于描述一个 QA 任务如何被 Runtime 执行，包括入口意图、输入契约、节点列表、节点输入输出、路由条件、产物写入、失败策略、版本策略和确认门禁。

## 当前可执行 DSL

Runtime 当前实际读取 `workflows/runtime/*.workflow.yml`，并支持以下最小字段：

```yaml
id: analysis_and_testcases
name: 需求分析与测试用例生成
version: 1

input:
  prd_path: required
  user_input: required

state:
  task_type: mvp_analysis_testcases

nodes:
  - id: command_router
    type: python
    handler: runtime.graph.nodes.mvp_context_loader.mvp_command_router_node

edges:
  - from: start
    to: command_router

  - from: command_router
    to: end
    condition: default
```

当前 Runtime 约束：

- `id`、`name`、`version`、`nodes`、`edges` 为必填字段。
- `version` 必须为大于等于 1 的整数。
- `nodes[].type` 当前只支持 `python`。
- `nodes[].handler` 必须是可动态 import 的 Python callable。
- `edges[].from` 可以是 `start` 或已声明 node id。
- `edges[].to` 可以是 `end` 或已声明 node id。
- 同一 workflow 不允许重复 `node id` 或重复 `edge`。
- 同一 `from` 不允许混合无条件固定边和条件边。
- 同一 `from` 最多只能有一条 `condition: default` 边。
- 条件边先按 YAML 顺序评估普通 condition，全部不命中时才走 `default`。没有显式 `default` 时，为兼容旧 MVP DSL，Runtime 会隐式路由到 `end`。

### 当前内置 condition

| condition | 含义 |
|---|---|
| `no_errors` | `errors` 为空 |
| `has_errors` | `errors` 非空 |
| `no_quality_errors` | `errors` 和 `quality_errors` 均为空 |
| `task_is_analysis` | 当前任务为需求分析 |
| `task_is_testcase_generation` | 当前任务为测试用例生成 |
| `task_is_analysis_or_mvp` | 当前任务为需求分析或需求分析加用例生成 |
| `task_is_mvp` | 当前任务为需求分析加用例生成，且无质量错误 |
| `needs_human_review_or_approved` | `approved/write_approved` 且 `next_action=promote` 时允许写入候选产物 |
| `default` | 条件边兜底分支 |

### 当前 Runtime workflow 文件

| workflow_id | 文件 | task_type |
|---|---|---|
| `analysis_and_testcases` | `workflows/runtime/analysis-and-testcases.workflow.yml` | `mvp_analysis_testcases` |
| `requirement_analysis` | `workflows/runtime/requirement-analysis.workflow.yml` | `analysis` |
| `testcase_generation` | `workflows/runtime/testcase-generation.workflow.yml` | `testcase_generation` |

## 最小工作流示例

```yaml
id: requirement_to_testcases
name: 需求分析与测试用例生成
version: 1.0.0
description: 根据需求文档生成需求分析和测试用例，并进入确认门禁。

trigger:
  intents:
    - analyze_requirement
    - generate_testcases
    - analyze_and_generate_testcases
  entrypoints:
    - ai_chat
    - feishu_bot
    - wechat_bot
    - dingtalk_bot
    - cli
    - api

execution_policy:
  idempotency: true
  resume_from_checkpoint: true
  atomic_artifact_write: true
  persist_partial_output: true
  default_timeout_seconds: 300
  default_max_attempts: 1

artifact_policy:
  write_mode: versioned_atomic
  on_partial: persist_to_run
  on_success: promote_preview_to_current
  on_failure: keep_current_artifact
  versioning: true
  history_dir: artifacts/history
  preview_path: runs/<run-id>/artifact-preview.md
  diff_path: runs/<run-id>/diff.md
  on_promote:
    archive_previous: true
    mark_previous_as: superseded
    update_history_index: true
    update_metadata: true

input_contract:
  required:
    prd_path:
      type: string
      description: 需求工作区路径，例如 prd/demo-requirement
    user_message:
      type: string
      description: 用户原始输入
  optional:
    profile:
      type: string
      default: local

output_contract:
  artifacts:
    - path: artifacts/requirement-analysis.md
      type: requirement_analysis
      review_required: true
    - path: artifacts/testcases.md
      type: testcases
      review_required: true
  run_record:
    path: runs/<run-id>/state.json
  review_records:
    - reviews/requirement-analysis.review.yml
    - reviews/testcases.review.yml

state_schema:
  prd_path: string
  user_message: string
  intent: string
  normalized_requirement: object
  retrieved_context: array
  requirement_analysis: object
  testcases: object
  quality_result: object
  review_status: string
  artifacts: array
  errors: array

nodes:
  - id: load_requirement
    type: tool
    required: true
    tool: workspace.load_requirement
    failure_policy:
      on_error: fail_workflow
      timeout_seconds: 60
    input:
      prd_path: "{{ state.prd_path }}"
      requirement_path: input/requirement.md
      api_path: input/api.md
    output:
      normalized_requirement: "{{ result.normalized_requirement }}"

  - id: retrieve_context
    type: rag
    required: false
    failure_policy:
      on_error: fallback
      fallback_node: build_context_from_requirement_only
      max_attempts: 2
      retry_backoff_seconds: 2
    input:
      query: "{{ state.user_message }}"
      prd_path: "{{ state.prd_path }}"
      sources:
        - rules
        - skills
        - prompts
        - workflows
        - knowledge
        - "{{ state.prd_path }}/input"
      top_k: 8
    output:
      retrieved_context: "{{ result.chunks }}"

  - id: generate_requirement_analysis
    type: agent
    required: true
    agent: requirement_analysis_agent
    failure_policy:
      on_error: retry
      max_attempts: 2
      retry_backoff_seconds: 3
      timeout_seconds: 180
      fallback: wait_for_user
    input:
      requirement: "{{ state.normalized_requirement }}"
      context: "{{ state.retrieved_context }}"
    output:
      requirement_analysis: "{{ result.analysis }}"

  - id: generate_testcases
    type: agent
    required: true
    agent: testcase_design_agent
    failure_policy:
      on_error: retry
      max_attempts: 2
      retry_backoff_seconds: 3
      timeout_seconds: 180
      fallback: wait_for_user
    input:
      requirement: "{{ state.normalized_requirement }}"
      analysis: "{{ state.requirement_analysis }}"
      context: "{{ state.retrieved_context }}"
    output:
      testcases: "{{ result.testcases }}"

  - id: quality_check
    type: validator
    required: true
    validator: artifact_quality_validator
    failure_policy:
      on_error: fail_workflow
    input:
      artifacts:
        - "{{ state.requirement_analysis }}"
        - "{{ state.testcases }}"
      rules:
        - rules/artifact-standards.md
        - rules/testcase-standards.md
    output:
      quality_result: "{{ result }}"

  - id: write_artifact_preview
    type: writer
    required: true
    tool: workspace.write_artifact_preview
    input:
      prd_path: "{{ state.prd_path }}"
      preview_path: runs/<run-id>/artifact-preview.md
      artifacts:
        - path: artifacts/requirement-analysis.md
          content: "{{ state.requirement_analysis }}"
        - path: artifacts/testcases.md
          content: "{{ state.testcases }}"
    output:
      preview_path: "{{ result.preview_path }}"

  - id: create_review_records
    type: tool
    required: true
    tool: workspace.create_review_records
    input:
      prd_path: "{{ state.prd_path }}"
      artifacts:
        - artifacts/requirement-analysis.md
        - artifacts/testcases.md
      status: needs_human_review
    output:
      review_status: needs_human_review

  - id: wait_for_confirmation
    type: review_gate
    required: true
    input:
      prd_path: "{{ state.prd_path }}"
      artifacts:
        - artifacts/requirement-analysis.md
        - artifacts/testcases.md
    output:
      review_status: "{{ result.status }}"
      next_action: "{{ result.next_action }}"

  - id: promote_artifacts
    type: writer
    required: true
    tool: workspace.promote_artifacts
    input:
      prd_path: "{{ state.prd_path }}"
      preview_path: runs/<run-id>/artifact-preview.md
      write_mode: versioned_atomic
    output:
      artifacts: "{{ result.artifacts }}"

edges:
  - from: start
    to: load_requirement
  - from: load_requirement
    to: retrieve_context
  - from: retrieve_context
    to: generate_requirement_analysis
  - from: generate_requirement_analysis
    to: generate_testcases
  - from: generate_testcases
    to: quality_check
  - from: quality_check
    to: review_gate
    condition: "{{ state.quality_result.passed == true }}"
  - from: quality_check
    to: failed
    condition: "{{ state.quality_result.passed == false }}"
  - from: review_gate
    to: write_artifact_preview
    condition: "{{ state.review_status == 'approved' and state.next_action == 'promote' }}"
  - from: review_gate
    to: generate_testcases
    condition: "{{ state.next_action == 'revise' }}"
  - from: review_gate
    to: failed
    condition: "{{ state.next_action == 'stop' }}"
  - from: write_artifact_preview
    to: end
```

## 节点类型

| 节点类型 | 说明 |
|---|---|
| `tool` | 确定性工具节点，例如读取文件、创建确认记录、执行测试 |
| `rag` | RAG 检索节点，负责文档加载、检索、筛选和上下文构建 |
| `agent` | LLM Agent 节点，负责需求分析、用例生成、失败分析、报告生成等任务 |
| `validator` | 质量检查节点，负责校验产物格式、字段、状态、覆盖度和规则约束 |
| `review_gate` | 确认门禁节点，负责读取用户确认结果并决定后续流转 |
| `router` | 路由节点，根据状态、意图或校验结果选择下一节点 |
| `executor` | 执行节点，例如运行 pytest、Playwright 或其他测试命令 |
| `writer` | 产物写入节点，负责候选产物、正式产物和版本索引写入 |
| `terminator` | 结束节点，用于标记成功、失败、中断或等待确认 |

## 路由原则

`needs_human_review` 必须由 `review_gate` 调用 LangGraph interrupt 暂停，不能进入 `end`。`approved` 只允许写入候选 preview 并准备独立 promote；`confirmed` 只能由 `promote_artifacts` 成功后设置。

正式产物发布必须经过以下顺序：

```text
write_artifact_preview
  ↓
create_review_records
  ↓
promote_artifacts
  ↓
confirmed
```
