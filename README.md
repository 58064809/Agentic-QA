# Agentic-QA

Agentic-QA 是面向测试工程师的 Agentic QA Engineering 项目。当前 Runtime 将自然语言需求转换为可追踪、可审核、可恢复的 QA 候选产物，并通过 Review Gate 和确定性 promote 管理正式版本。

## 当前已接入能力

- 需求分析
- 测试用例生成
- 需求分析 + 测试用例联合生成
- API 测试草稿
- RAG 接口自动化 YAML 用例
- UI 自动化草稿
- 网络抓包接口发现报告
- QA 报告草稿
- RAG 检索与来源追踪
- LangGraph interrupt、checkpoint 与恢复
- 候选产物拆分、审核、发布和历史版本

未接入 `workflows/runtime/` 的能力不视为当前可执行功能。

## 执行链路

```text
Chat / Bot / CLI / API
  -> 意图识别
  -> Workflow Registry
  -> workflows/runtime/*.workflow.yml
  -> 上下文与 RAG
  -> QA Agent 生成
  -> 质量检查
  -> runs/<run-id>/<artifact>.preview.md
  -> Review Gate interrupt
  -> approved / needs_changes / rejected
  -> approved 后确定性 promote
  -> artifacts/<artifact>.md
  -> history + review + metadata
```

原则：LLM 负责理解和生成，程序负责 Schema、状态、路径、Review Gate 与正式写入。

## 当前工作区

```text
prd/<id>/
├── input/
│   ├── requirement.md
│   ├── api.md
│   └── attachments/
├── artifacts/
│   ├── requirement-analysis.md
│   ├── testcases.md
│   ├── api-test-draft.md
│   ├── api-test-cases.yml
│   ├── ui-test-draft.md
│   ├── api-discovery-report.md
│   ├── qa-report.md
│   └── history/<artifact>/
├── reviews/
│   └── <artifact>.review.yml
├── runs/
│   ├── latest.yml
│   ├── index.jsonl
│   └── <run-id>/
│       ├── artifact-preview.md
│       ├── <artifact>.preview.md
│       ├── <artifact>.preview.yml/json
│       └── api-test-cases.yml
└── metadata.yml
```

`artifact-preview.md` 只保存本次 run 的候选索引；候选正文必须拆分为 `<artifact>.preview.md`。

Runtime 内部状态、RAG trace、review events 和 checkpoint 元数据保存到 `.runtime/runs/<run-id>/`。

## 事实源

| 契约 | 权威实现 |
|---|---|
| Workflow | `workflows/runtime/*.workflow.yml` |
| Workflow Schema/构图 | `runtime/workflow/` |
| 任务与上下文映射 | `runtime/workflow/catalog.py` |
| 工作区与 artifact 路径 | `runtime/workspace.py` |
| 结构化输入输出 | `runtime/schemas/`、`runtime/graph/state.py` |
| 强规则 | `rules/` |
| 模型任务指令 | `prompts/` |
| 可复用方法 | `skills/` |
| RAG 资产 | `knowledge/` |

文档与代码冲突时修正文档或删除旧文件，不增加兼容读取、双写或 fallback。

## 快速开始

Windows / PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
python scripts/create_prd_workspace.py demo-requirement
python -m runtime.cli "分析 prd/demo-requirement 并生成测试用例"
```

安装后也可使用：

```powershell
agentic-qa "分析 prd/demo-requirement 并生成测试用例"
```

## 常用任务

```text
分析 prd/demo-requirement 的需求，识别业务规则、风险和待确认项。
```

```text
基于 prd/demo-requirement 生成测试用例，覆盖正常、异常、边界和状态流转。
```

```text
基于 prd/demo-requirement 的需求和接口契约生成 API 测试草稿。
```

```text
prd/demo-requirement 的测试用例通过，发布正式产物。
```

完整入口见 [`COMMANDS.md`](COMMANDS.md)。

## 一致性检查 Loop

一次检查：

```powershell
python scripts/validate_docs_consistency.py
```

开发期间循环检查：

```powershell
python scripts/validate_docs_consistency.py --watch
```

检查内容包括：

- 旧 Workflow Markdown
- 旧路径、旧文件名和旧状态
- 重复 Prompt
- Runtime context 悬空引用
- Workspace 路径契约漂移
- Workflow YAML、condition 与 DSL 文档漂移
- Markdown 失效路径

CI 同时运行：

```powershell
python scripts/validate_prd_workspace.py prd/sample-login-requirement
pytest
ruff check .
```

## 文档导航

- [`AGENTS.md`](AGENTS.md)：Agent 执行规范与事实源优先级
- [`COMMANDS.md`](COMMANDS.md)：自然语言任务与 CLI
- [`docs/architecture.md`](docs/architecture.md)：当前架构
- [`docs/workflow-dsl.md`](docs/workflow-dsl.md)：可执行 Workflow DSL
- [`docs/prompt-engineering.md`](docs/prompt-engineering.md)：Prompt 治理
- [`docs/runtime-reliability.md`](docs/runtime-reliability.md)：失败、恢复和 checkpoint
- [`docs/artifact-versioning.md`](docs/artifact-versioning.md)：候选、正式和历史版本
- [`docs/review-gate.md`](docs/review-gate.md)：审核门
- [`docs/artifact-standards.md`](docs/artifact-standards.md)：产物标准
- [`docs/testcase-standards.md`](docs/testcase-standards.md)：测试用例标准
- [`docs/rag-design.md`](docs/rag-design.md)：RAG 设计
- [`docs/roadmap.md`](docs/roadmap.md)：后续建设项
