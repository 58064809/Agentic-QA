# Agentic-QA

**Agentic-QA** 是一个面向测试工程师的 **Agentic QA Engineering** 项目，用于构建 AI 辅助的软件测试工程工作流。

项目通过 Runtime 编排、配置层管理、RAG 上下文检索、专业 QA Agent、测试方法论、规则约束和人工审核机制，帮助测试工程师将需求文档转化为结构化的需求分析、测试用例、自动化脚本草稿、执行记录、失败分析、Bug 草稿、QA 报告和可复用知识资产。

## 核心能力

- **自然语言任务入口**：支持通过 AI 编辑器 Chat、飞书 Bot、微信 Bot、钉钉 Bot、CLI 或 API 发起 QA 任务。
- **配置层管理**：统一管理 Runtime、RAG、LLM、工作区、协作入口、日志和运行 Profile。
- **需求文档归一化**：将 Word、PDF、TXT、HTML 等需求来源转换为统一的 Markdown 输入。
- **意图识别**：识别用户输入的 QA 任务目标，例如需求分析、测试用例生成、接口测试生成、失败分析或报告生成。
- **工作流选择**：根据任务意图匹配对应的 QA 工作流。
- **Runtime 编排**：负责任务执行、节点流转、状态管理、质量检查、人工审核和产物写入。
- **RAG 上下文检索**：从需求、接口文档、规则、Skills、Prompts、Knowledge 和历史资产中检索相关上下文。
- **专业 QA Agent**：覆盖需求分析、测试设计、接口测试生成、UI 测试生成、测试执行、失败分析、Bug 草稿和 QA 报告等任务。
- **测试方法论沉淀**：内置等价类、边界值、场景法、状态迁移、风险测试、接口契约分析等测试设计能力。
- **人工审核门禁**：AI 生成产物默认进入待审核状态，由测试工程师确认后再进入下一步。
- **需求工作区管理**：每个需求拥有独立工作区，统一管理输入、产物、审核状态、运行记录和归档资产。
- **运行记录追踪**：记录每次 Runtime 执行的输入、节点轨迹、召回上下文、输出路径、错误和告警。

## 工作流

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
人工审核
  ↓
产物写入
  ↓
运行记录 / 元数据更新
```

## 架构概览

```text
入口层
├── AI 编辑器 Chat
│   ├── Cursor
│   ├── Codex
│   ├── ChatGPT
│   ├── Claude Code
│   └── PyCharm AI Chat
├── 协作 Bot
│   ├── 飞书 Bot
│   ├── 微信 Bot
│   └── 钉钉 Bot
├── CLI
└── API

配置层
├── 运行配置
├── Profile 配置
├── 工作区配置
├── RAG 配置
├── LLM 配置
├── Bot / API 配置
└── 日志配置

Runtime
├── 意图识别
├── 工作流选择
├── 工作流编排
├── 状态管理
├── 质量检查
├── 人工审核门禁
├── 产物写入
└── 运行记录

RAG
├── 文档加载
├── 文档切分
├── 索引构建
├── 上下文检索
├── 结果筛选 / 重排
└── 上下文构建

QA Agent
├── 需求分析 Agent
├── 测试用例设计 Agent
├── 接口测试生成 Agent
├── UI 测试生成 Agent
├── 测试执行 Agent
├── 失败分析 Agent
├── Bug 草稿 Agent
└── QA 报告 Agent

知识资产
├── rules/
├── skills/
├── prompts/
├── workflows/
├── knowledge/
└── prd/
```

## 需求工作区

每个需求使用独立工作区管理输入、产物、审核状态和运行记录。

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
│   └── archive-index.md
├── reviews/
│   ├── requirement-analysis.review.yml
│   ├── testcases.review.yml
│   ├── api-test-draft.review.yml
│   ├── ui-test-draft.review.yml
│   ├── failure-analysis.review.yml
│   ├── bug-draft.review.yml
│   └── qa-report.review.yml
├── runs/
│   └── <run-id>/
│       ├── state.json
│       ├── events.jsonl
│       ├── retrieved-context.json
│       ├── prompt.md
│       ├── output.md
│       └── quality-check.json
└── metadata.yml
```

### input/

`input/` 保存当前需求的原始输入和归一化输入。

| 文件 | 说明 |
|---|---|
| `requirement.md` | 需求正文 |
| `api.md` | 接口文档 |
| `attachments/` | 原型图、补充文档、截图等附件 |

### artifacts/

`artifacts/` 保存 Runtime 生成或人工确认后的 QA 产物。

| 文件 | 说明 |
|---|---|
| `requirement-analysis.md` | 需求分析 |
| `testcases.md` | 测试用例 |
| `api-test-draft.md` | 接口测试脚本草稿或生成计划 |
| `ui-test-draft.md` | UI 测试脚本草稿或生成计划 |
| `execution-report.md` | 测试执行报告 |
| `failure-analysis.md` | 失败分析 |
| `bug-draft.md` | Bug 草稿 |
| `qa-report.md` | QA 报告 |
| `archive-index.md` | 归档索引 |

### reviews/

`reviews/` 保存每个产物的审核状态、审核意见和确认记录。

示例：

```yaml
artifact: artifacts/testcases.md
status: needs_human_review
reviewer: ""
comments: []
approved_at: null
```

### runs/

`runs/` 保存 Runtime 每次执行的运行记录，包括状态、事件、召回上下文、Prompt、输出和质量检查结果。

### metadata.yml

`metadata.yml` 保存需求级元数据，例如需求名称、状态、创建时间、最后运行记录、关联产物和归档状态。

## 配置层

Agentic-QA 使用配置层统一管理 Runtime、RAG、LLM、工作区、协作入口和日志参数。

```text
config/
├── default.yml
├── profiles/
│   ├── local.yml
│   ├── dev.yml
│   └── ci.yml
└── examples/
    ├── llm.example.yml
    ├── rag.example.yml
    ├── integrations.example.yml
    └── workspace.example.yml
```

配置加载优先级：

```text
内置默认值
  ↓
config/default.yml
  ↓
config/profiles/<profile>.yml
  ↓
需求工作区 metadata.yml
  ↓
环境变量
  ↓
CLI 参数 / Bot 请求参数
```

配置层只管理系统运行参数，不承载测试知识和业务规则。

| 类型 | 归属 |
|---|---|
| Runtime、RAG、LLM、日志、工作区、Bot/API 参数 | `config/` |
| 产物格式、路径、审核、质量强约束 | `rules/` |
| 测试方法论和专业能力 | `skills/` |
| 可检索领域知识、模板和历史经验 | `knowledge/` |
| 模型提示词模板 | `prompts/` |

密钥类配置只允许通过环境变量读取，不写入配置文件、运行记录、日志或生成产物。

## 项目结构

| 路径 | 说明 |
|---|---|
| `config/` | 项目运行配置、Profile 配置和示例配置 |
| `runtime/` | Runtime 主体代码，负责工作流编排和执行 |
| `runtime/config/` | 配置加载、合并、校验和环境变量解析 |
| `runtime/intent/` | 意图识别、任务解析和结构化任务结果 |
| `runtime/workflow/` | 工作流选择、注册和执行入口 |
| `runtime/graph/` | 工作流图、节点、状态和路由 |
| `runtime/rag/` | 文档切分、索引、检索和上下文选择 |
| `runtime/agents/` | 可执行 QA Agent 节点或 Agent 适配 |
| `runtime/llm/` | LLM 调用抽象和模型适配 |
| `runtime/tools/` | 文件读写、产物写入、测试执行和报告工具 |
| `runtime/schemas/` | 结构化输入输出 Schema |
| `integrations/` | 飞书、微信、钉钉、API 等外部入口适配 |
| `workflows/` | 声明式 QA 工作流定义 |
| `prompts/` | Prompt 模板 |
| `rules/` | 路径、输出、审核和质量强约束 |
| `skills/` | 可复用 QA 技能和测试方法 |
| `knowledge/` | RAG 知识库 |
| `prd/` | 需求工作区和生成产物 |
| `scripts/` | 校验、执行、报告和归档辅助脚本 |
| `tests/` | 单元测试和 Runtime 测试 |
| `docs/` | 架构设计、路线图和使用说明 |

## RAG 说明

Agentic-QA 的 RAG 链路用于从项目知识资产和需求上下文中检索与当前任务相关的材料。

核心流程：

```text
Document Load
  ↓
Chunk
  ↓
Index
  ↓
Retrieve
  ↓
Select / Rerank
  ↓
Context Build
  ↓
Generate
```

RAG 结果应保留可追踪信息，包括：

- 召回来源
- chunk 标识
- 命中依据或分数
- 参与生成的上下文
- 信息不足或未召回告警

## 产物规范

AI 生成产物默认包含审核元数据：

```yaml
status: needs_human_review
human_review_required: true
```

测试用例表格固定使用以下列：

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|

优先级统一使用：

```text
P0 / P1 / P2 / P3
```

## 人工审核

Agentic-QA 采用人机协同流程。

以下产物进入下一步前必须经过人工审核：

- 需求分析
- 测试用例
- 接口自动化脚本草稿
- UI 自动化脚本草稿
- 测试执行范围
- 失败分析
- Bug 草稿
- QA 报告
- 归档记录

## 快速开始

安装本地开发包：

```bash
pip install -e .
```

创建需求工作区：

```bash
python scripts/create_prd_workspace.py demo-requirement
```

将需求文档放入：

```text
prd/demo-requirement/input/requirement.md
```

可选接口文档放入：

```text
prd/demo-requirement/input/api.md
```

校验仓库和需求工作区：

```bash
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/demo-requirement
```

### 通过 AI Chat 发起任务

在 Cursor、Codex、ChatGPT、Claude Code、PyCharm AI Chat 等工具中，可以用自然语言发起 QA 任务：

```text
分析 prd/demo-requirement 这个需求，生成需求分析。
```

```text
基于 prd/demo-requirement 的需求分析生成测试用例。
```

```text
分析 prd/demo-requirement，并生成需求分析和测试用例，产物写入需求工作区。
```

### 通过协作 Bot 发起任务

飞书 Bot、微信 Bot、钉钉 Bot 可以作为团队协作入口，将用户消息、需求链接或附件转发给 Runtime。

示例：

```text
分析这个需求文档，生成需求分析和测试用例。
```

```text
读取这个飞书文档，生成测试用例草稿。
```

```text
根据这个需求链接生成 QA 报告草稿。
```

### 使用 CLI 调试 Runtime

CLI 主要用于本地调试、脚本化执行和 Runtime 能力验证：

```bash
python -m runtime.cli analyze "分析这个需求" --prd prd/demo-requirement
```

```bash
python -m runtime.cli generate-testcases "生成测试用例" --prd prd/demo-requirement
```

```bash
python -m runtime.cli run "分析需求并生成测试用例" --prd prd/demo-requirement
```

确认写入产物：

```bash
python -m runtime.cli run "分析需求并生成测试用例" --prd prd/demo-requirement --confirm
```

运行基础检查：

```bash
pytest
ruff check .
```

## LLM 配置

Runtime 从本地环境变量读取模型配置。

示例：

```bash
FREEMODEL_API_KEY=your-local-key
FREEMODEL_BASE_URL=https://api.example.com/v1
FREEMODEL_MODEL=your-model-name
```

密钥不得写入仓库，也不得写入运行记录、日志或生成产物。

## 建设路线图

```text
工程底座
├── 配置层
├── 需求工作区
├── 运行记录
├── 产物写入
└── 审核状态管理

Runtime
├── 意图识别
├── 工作流选择
├── 工作流编排
├── 状态流转
├── 质量检查
└── 人工审核门禁

RAG
├── 文档加载
├── Markdown 切分
├── 索引构建
├── 上下文检索
├── 召回结果追踪
└── 上下文预算控制

QA 生成能力
├── 需求分析生成
├── 测试用例生成
├── 接口测试生成
├── UI 测试生成
├── 失败分析生成
├── Bug 草稿生成
└── QA 报告生成

测试执行能力
├── pytest 执行
├── Playwright 执行
├── 执行结果收集
├── 失败归因
└── 报告汇总

协作入口
├── AI 编辑器 Chat
├── 飞书 Bot
├── 微信 Bot
├── 钉钉 Bot
├── API
└── Web

知识沉淀
├── 需求资产归档
├── 历史用例复用
├── 缺陷经验沉淀
├── 项目规则沉淀
└── RAG 知识库持续更新
```

## 项目愿景

Agentic-QA 的目标是让 AI 参与完整 QA 工程生命周期，从需求理解、测试设计、自动化生成，到执行分析、报告归档和知识复用，逐步沉淀为可运行、可追踪、可扩展的智能测试工程体系。
