# Agentic-QA

Agentic-QA 把自然语言 QA 任务编排成可追踪、可审核的 LangGraph 工作流。当前 Runtime 以 `workflows/runtime/*.workflow.yml` 为唯一流程定义；所有生成结果先写入候选区，只有通过 Review Gate 后才能发布为正式产物。

## 当前能力

| 意图 | WorkflowSpec | 候选产物 |
|---|---|---|
| 需求分析 | `requirement_analysis` | `requirement-analysis.preview.md` |
| 测试用例 | `testcase_generation` | `testcases.preview.md` |
| 需求分析 + 测试用例 | `analysis_and_testcases` | 拆分后的需求候选和用例候选 |
| API 测试草稿 | `api_test_draft` | Markdown 草稿；有契约时附 API YAML |
| RAG API 自动化用例 | `rag_automation_case_generation` | API YAML 与 RAG run record |
| UI 自动化草稿 | `ui_test_draft` | `ui-test-draft.preview.md` |
| 接口发现报告 | `api_discovery_report` | `api-discovery-report.preview.md` |
| QA 报告 | `qa_report` | `qa-report.preview.md` |

测试执行、失败分析、缺陷草稿和归档编排不属于当前 Runtime 能力；路线图中的后续项不得当作已实现入口。

## 唯一主链路

```text
自然语言
  -> intent
  -> workflows/runtime/*.workflow.yml
  -> LangGraph QAWorkflowState
  -> 质量门
  -> prd/<id>/runs/<run_id>/<artifact>.preview.md
  -> prd/<id>/runs/<run_id>/artifact-preview.md 索引
  -> metadata.yml + reviews/*.review.yml
  -> Review Gate interrupt
  -> approved
  -> promote
  -> prd/<id>/artifacts/
```

约束：

- Python 不维护第二套工作流或 Prompt 契约。
- `prompts/` 中每种生成能力只保留一份 canonical Prompt。
- 未确认内容不得写入 `artifacts/`。
- `confirmed` 只能由确定性 promote 成功后产生。
- 缺少 API 契约时不得猜测 method、path、参数或断言；只有完整 OpenAPI 可以进入 `confirmed` 契约状态。
- API YAML 只接受 `agentic-qa.api-cases.v1.1`。

## 工作区

```text
prd/<需求ID>/
├── input/
│   ├── requirement.md
│   ├── api.md
│   └── attachments/
├── runs/
│   ├── latest.yml
│   ├── index.jsonl
│   └── <run_id>/
│       ├── artifact-preview.md
│       ├── artifact-preview.json
│       ├── artifact-preview.yml
│       ├── requirement-analysis.preview.md
│       ├── testcases.preview.md
│       └── <artifact>.preview.yml/json
├── reviews/
├── artifacts/
│   ├── requirement-analysis.md
│   ├── testcases.md
│   ├── api-test-draft.md
│   ├── ui-test-draft.md
│   ├── api-discovery-report.md
│   ├── qa-report.md
│   └── history/
└── metadata.yml
```

`.runtime/runs/<run_id>/` 保存内部 graph state、checkpoint、review events 和运行摘要；`prd/<id>/runs/` 保存用户可审核的候选产物及需求级索引。

## 安装

```bash
python -m venv .venv
pip install -e ".[dev]"
```

按需安装：

```bash
pip install -e ".[rag]"        # FAISS
pip install -e ".[postgres]"   # PostgreSQL checkpoint
pip install -e ".[documents]"  # Office/PDF 转 Markdown
pip install -e ".[feishu]"     # 飞书 docx 导入
pip install -e ".[full,dev]"   # 全部可选能力
```

## 使用

创建并校验工作区：

```bash
python scripts/create_prd_workspace.py demo-requirement
python scripts/validate_prd_workspace.py prd/demo-requirement
```

生成候选产物：

```bash
python -m runtime.cli "分析 prd/demo-requirement 并生成测试用例"
```

审核并发布：

```bash
python -m runtime.cli resume <run_id> "全部通过，全部发布"
python -m runtime.cli promote prd/demo-requirement <run_id> testcases
```

RAG 调试：

```bash
python -m runtime.cli rag status
python -m runtime.cli rag build
python -m runtime.cli rag search "边界值 活动规则"
```

## 验证

```bash
ruff check .
python scripts/validate_docs_consistency.py
pytest -q
```

## 文档边界

| 文档 | 负责内容 |
|---|---|
| [架构](docs/architecture.md) | 分层、唯一主链路与边界 |
| [Workflow DSL](docs/workflow-dsl.md) | YAML Schema、节点、条件边与失败策略 |
| [Review Gate](docs/review-gate.md) | 审核状态机与 promote 规则 |
| [运行可靠性](docs/runtime-reliability.md) | checkpoint、重试、幂等与运行记录 |
| [产物版本](docs/artifact-versioning.md) | 候选、正式产物与历史版本 |
| [测试用例标准](docs/testcase-standards.md) | 11 列用例契约与质量门 |
| [API 测试生成](docs/api-test-generation.md) | 契约状态与 API YAML v1.1 |
| [RAG 设计](docs/rag-design.md) | 索引、检索、上下文和 trace |
| [Prompt 工程](docs/prompt-engineering.md) | Prompt 单一事实源和治理规则 |
| [命令入口](COMMANDS.md) | 当前自然语言与 CLI 用法 |
| [路线图](docs/roadmap.md) | 已实现范围与下一阶段 |
