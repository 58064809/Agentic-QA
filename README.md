# Agentic-QA

**Agentic-QA** 是一个面向测试工程师的 **Agentic QA Engineering** 项目，用于构建 AI 辅助的软件测试工程工作流。

项目通过自然语言入口、Runtime 编排、配置层管理、RAG 上下文检索、专业 QA Agent、测试方法论、规则约束和确认机制，帮助测试工程师将需求文档转化为结构化的需求分析、测试用例、自动化脚本草稿、执行记录、失败分析、Bug 草稿、QA 报告和可复用知识资产。

Agentic-QA 的最终目标是让用户通过 **Chat、Bot 或 CLI** 以自然语言完成需求分析、测试设计、用例生成、自动化生成、测试执行、失败分析、缺陷草稿、报告和归档等测试活动。用户不需要手动维护流程状态、产物路径或运行记录，Runtime 负责将自然语言意图转换为可追踪、可执行、可审核、可恢复的工程化工作流。

## 核心能力

- **统一自然语言入口**：AI Chat、Bot、CLI 和 API 都只是入口形态，Runtime 统一负责意图识别、工作流选择和任务执行。
- **配置层管理**：统一管理 Runtime、RAG、LLM、工作区、协作入口、日志和运行 Profile。
- **意图识别与工作流选择**：识别用户输入的 QA 任务目标，并匹配对应 QA 工作流。
- **Runtime 编排**：负责任务执行、节点流转、状态管理、质量检查、确认门禁和产物写入。
- **运行可靠性策略**：支持节点失败处理、重试、降级、部分产物保留、原子写入、幂等执行和恢复。
- **产物版本管理**：正式产物保持稳定路径，修订结果先生成候选版本，确认后再提升为当前版本，历史版本可追溯。
- **RAG 上下文检索**：当前采用“确定性上下文加载 + 知识库向量检索”的混合模式，后续可扩展为统一索引式 RAG。
- **专业 QA Agent**：覆盖需求分析、测试设计、接口测试生成、UI 测试生成、测试执行、失败分析、Bug 草稿和 QA 报告等任务。
- **自然语言确认机制**：用户可通过 Chat、Bot 或 CLI 表达通过、修改、驳回、继续执行等确认意图。

## Review Gate 原则

Review Gate 遵循“LLM 负责理解，程序负责裁决”的边界：LLM 或语义解析器只能把用户自然语言转换为结构化 `ReviewDecision`，不能直接写入 `artifacts/`、不能直接把状态改成 `confirmed`、不能执行 promote。

正式流转由确定性状态机控制：候选产物进入 `needs_human_review` 后，用户确认只会把目标 review 更新为 `approved`；正式发布仍必须由确定性 `promote` 命令或函数执行，成功后才会写入正式产物并标记 `confirmed`。

## 工作流主链路

```text
用户输入 / AI Chat / Bot / CLI / API
  ↓
意图识别
  ↓
工作流选择
  ↓
工作流编排
  ↓
需求加载
  ↓
文档归一化
  ↓
RAG 检索
  ↓
上下文构建
  ↓
QA Agent 执行
  ↓
质量检查
  ↓
写入候选产物 artifact-preview
  ↓
确认门禁 Review Gate
  ↓
发布正式产物 / 进入修订 / 等待确认
  ↓
运行记录 / 元数据更新
```

关键原则：**修订工作流不得直接覆盖正式产物**。Runtime 必须先生成候选版本，经过质量检查和确认门禁后，才允许将候选版本提升为当前正式版本。

## 架构概览

![Agentic-QA 架构图](docs/assets/agentic-qa-architecture.png)

```text
入口层
├── AI 编辑器 Chat
├── 飞书 Bot / 微信 Bot / 钉钉 Bot
├── CLI
└── API

配置层
├── Runtime 配置
├── RAG 配置
├── LLM 配置
├── 工作区配置
└── 协作入口配置

Runtime
├── 意图识别
├── 工作流选择
├── 工作流编排
├── 状态管理
├── 质量检查
├── 失败处理
├── 幂等与恢复
├── 确认门禁
├── 产物版本管理
└── 运行记录

知识资产
├── rules/
├── skills/
├── prompts/
├── workflows/
├── knowledge/
└── prd/
```

## 需求工作区

每个需求使用独立工作区管理输入、产物、确认状态、历史版本和运行记录。

```text
prd/<需求ID>/
├── input/
│   ├── requirement.md
│   ├── api.md
│   └── attachments/
├── artifacts/
│   ├── requirement-analysis.md
│   ├── testcases.md
│   ├── api-test-draft.md
│   ├── ui-test-draft.md
│   ├── execution-report.md
│   ├── failure-analysis.md
│   ├── bug-draft.md
│   ├── qa-report.md
│   ├── archive-index.md
│   └── history/
│       └── testcases/
│           ├── testcases.v1.md
│           ├── testcases.v2.md
│           └── index.yml
├── reviews/
│   ├── requirement-analysis.review.yml
│   ├── testcases.review.yml
│   └── qa-report.review.yml
├── runs/
│   ├── latest.yml
│   ├── index.jsonl
│   └── <run-id>/
│       ├── artifact-preview.md
│       ├── artifact-preview.json
│       └── artifact-preview.yml
└── metadata.yml
```

Runtime 内部执行记录当前保存到 `.runtime/runs/<run-id>/`：

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

## 项目结构

| 路径 | 说明 |
|---|---|
| `configs/` | 项目运行配置、Profile 配置和示例配置 |
| `runtime/` | Runtime 主体代码，负责工作流编排和执行 |
| `runtime/config.py` | 配置加载、合并、校验和环境变量解析 |
| `runtime/llm/intent_router.py`、`runtime/graph/nodes/intent_router.py` | 意图识别、任务解析和结构化任务结果 |
| `runtime/workflow/` | 工作流选择、注册和执行入口 |
| `runtime/graph/` | 工作流图、节点、状态和路由 |
| `rag/` | 文档切分、索引、检索和上下文选择 |
| `runtime/graph/nodes/` | 可执行 QA Agent 节点、工具节点和 Runtime 编排节点 |
| `runtime/llm/` | LLM 调用抽象和模型适配 |
| `runtime/tools/` | 文件读写、产物写入、测试执行和报告工具 |
| `runtime/schemas/` | 结构化输入输出 Schema |
| `integrations/` | 飞书、微信、钉钉、API 等外部入口适配 |
| `workflows/` | QA 工作流定义、流程配置和执行策略 |
| `prompts/` | Prompt 模板 |
| `rules/` | 路径、输出、确认门禁、版本策略和质量强约束 |
| `skills/` | 可复用 QA 技能和测试方法 |
| `knowledge/` | RAG 知识库 |
| `prd/` | 需求工作区和生成产物 |
| `scripts/` | 校验、执行、报告和归档辅助脚本 |
| `tests/` | 单元测试和 Runtime 测试 |
| `docs/` | 架构设计、路线图和使用说明 |

## 快速开始

推荐先创建本地虚拟环境并安装项目：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

PowerShell 也可以使用：

```bash
.venv\Scripts\Activate.ps1
```

创建需求工作区：

```bash
python scripts/create_prd_workspace.py demo-requirement
```

将需求文档写入：

```text
prd/demo-requirement/input/requirement.md
```

校验需求工作区：

```bash
python scripts/validate_prd_workspace.py prd/demo-requirement
```

安装后可以使用两种本地入口：

```bash
agentic-qa "分析 prd/demo-requirement 并生成测试用例"
python -m runtime.cli "分析 prd/demo-requirement 并生成测试用例"
```

### 通过自然语言发起任务

Agentic-QA 的主要使用方式是通过 AI Chat、Bot、CLI 或 API 输入自然语言任务，由 Runtime 统一完成意图识别、工作流选择、上下文构建、Agent 执行、质量检查、确认门禁和产物写入。

示例：

```text
分析 prd/demo-requirement 这个需求，并生成测试用例。
```

```text
读取这个飞书文档，生成需求分析和测试用例草稿。
```

```text
测试用例不通过，补充支付失败、库存不足和优惠券异常场景。
```

### 使用 CLI 调试 Runtime

CLI 是自然语言入口之一，主要用于本地调试、脚本化执行和最小 Runtime 验证。

```bash
python -m runtime.cli "分析 prd/demo-requirement 并生成测试用例"
```

运行基础检查：

```bash
pytest
ruff check .
```

## 设计文档

| 文档 | 说明 |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | 系统架构图、分层职责和主链路说明 |
| [`docs/workflow-dsl.md`](docs/workflow-dsl.md) | Workflow DSL、节点类型、输入输出契约和路由条件 |
| [`docs/runtime-reliability.md`](docs/runtime-reliability.md) | 节点失败策略、部分成功、原子写入、幂等和运行尝试 |
| [`docs/artifact-versioning.md`](docs/artifact-versioning.md) | 产物版本管理、候选版本、历史索引和发布策略 |
| [`docs/review-gate.md`](docs/review-gate.md) | 自然语言确认机制和 Review Gate Workflow |
| [`docs/artifact-standards.md`](docs/artifact-standards.md) | QA 产物标准、元数据和状态定义 |
| [`docs/testcase-standards.md`](docs/testcase-standards.md) | 测试用例结构、字段说明、优先级和质量要求 |
| [`docs/rag-design.md`](docs/rag-design.md) | RAG 链路、召回追踪和上下文构建 |
| [`docs/roadmap.md`](docs/roadmap.md) | 建设路线图 |

## 建设路线图

```text
工程底座
├── 配置层
├── 需求工作区
├── 运行记录
├── 产物写入
├── 产物版本管理
├── 历史追溯
├── 失败处理
├── 幂等与恢复
└── 确认状态管理

Runtime
├── 意图识别
├── 工作流选择
├── 工作流编排
├── 状态流转
├── 质量检查
└── Review Gate Workflow

QA 生成能力
├── 需求分析生成
├── 测试用例生成
├── 接口测试生成
├── UI 测试生成
├── 失败分析生成
├── Bug 草稿生成
└── QA 报告生成
```

## 项目愿景

Agentic-QA 的目标是让 AI 参与完整 QA 工程生命周期，从需求理解、测试设计、自动化生成，到执行分析、报告归档和知识复用，逐步沉淀为可运行、可追踪、可扩展的智能测试工程体系。
