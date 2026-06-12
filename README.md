# Agentic-QA

**Agentic-QA** 是一个面向测试工程师的 **Agentic QA Engineering** 项目，用于构建 AI 辅助的软件测试工程工作流。

项目通过自然语言入口、Runtime 编排、配置层管理、RAG 上下文检索、专业 QA Agent、测试方法论、规则约束和确认机制，帮助测试工程师将需求文档转化为结构化的需求分析、测试用例、自动化脚本草稿、执行记录、失败分析、Bug 草稿、QA 报告和可复用知识资产。

Agentic-QA 的最终目标是让用户通过 **Chat、Bot 或 CLI** 以自然语言完成需求分析、测试设计、用例生成、自动化生成、测试执行、失败分析、缺陷草稿、报告和归档等测试活动。用户不需要手动维护流程状态、产物路径或运行记录，Runtime 负责将自然语言意图转换为可追踪、可执行、可审核的工程化工作流。

## 核心能力

- **自然语言任务入口**：支持通过 AI 编辑器 Chat、飞书 Bot、微信 Bot、钉钉 Bot、CLI 或 API 发起 QA 任务。
- **配置层管理**：统一管理 Runtime、RAG、LLM、工作区、协作入口、日志和运行 Profile。
- **需求文档归一化**：将 Word、PDF、TXT、HTML 等需求来源转换为统一的 Markdown 输入。
- **意图识别**：识别用户输入的 QA 任务目标，例如需求分析、测试用例生成、接口测试生成、失败分析、产物确认或报告生成。
- **工作流选择**：根据任务意图匹配对应的 QA 工作流。
- **Runtime 编排**：负责任务执行、节点流转、状态管理、质量检查、确认门禁和产物写入。
- **RAG 上下文检索**：从需求、接口文档、规则、Skills、Prompts、Knowledge 和历史资产中检索相关上下文。
- **专业 QA Agent**：覆盖需求分析、测试设计、接口测试生成、UI 测试生成、测试执行、失败分析、Bug 草稿和 QA 报告等任务。
- **测试方法论沉淀**：内置等价类、边界值、场景法、状态迁移、风险测试、接口契约分析等测试设计能力。
- **自然语言确认机制**：用户可通过 Chat、Bot 或 CLI 表达通过、修改、驳回、继续执行等确认意图。
- **需求工作区管理**：每个需求拥有独立工作区，统一管理输入、产物、确认状态、运行记录和归档资产。
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
确认门禁
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
├── 确认门禁
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
├── QA 报告 Agent
└── 产物确认 Agent

知识资产
├── rules/
├── skills/
├── prompts/
├── workflows/
├── knowledge/
└── prd/
```

## 需求工作区

每个需求使用独立工作区管理输入、产物、确认状态和运行记录。

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

`artifacts/` 保存 Runtime 生成或用户确认后的 QA 产物。

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

`reviews/` 保存每个产物的确认状态、确认意见和结构化决策记录。

示例：

```yaml
artifact: artifacts/testcases.md
artifact_type: testcases
status: needs_human_review
reviewer: ""
reviewed_at: null
decision: ""
comments: []
required_changes: []
next_action: ""
source_message: ""
run_id: ""
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
| 产物格式、路径、确认门禁和质量强约束 | `rules/` |
| 测试方法论和专业能力 | `skills/` |
| 可检索领域知识、模板和历史经验 | `knowledge/` |
| 模型提示词模板 | `prompts/` |

LLM 配置属于配置层的一部分。模型名称、接口地址、超时时间、重试策略等可由 `config/default.yml` 和 Profile 配置管理；密钥类配置只允许通过环境变量读取。

示例：

```yaml
llm:
  enabled: false
  provider: openai_compatible
  model: ""
  base_url: ""
  api_key_env: FREEMODEL_API_KEY
  timeout_seconds: 180
  max_retries: 0
```

本地环境变量示例：

```bash
FREEMODEL_API_KEY=your-local-key
FREEMODEL_BASE_URL=https://api.example.com/v1
FREEMODEL_MODEL=your-model-name
```

密钥不得写入仓库，也不得写入运行记录、日志或生成产物。

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
| `workflows/` | QA 工作流定义、流程配置和执行策略 |
| `prompts/` | Prompt 模板 |
| `rules/` | 路径、输出、确认门禁和质量强约束 |
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

## 产物标准

Agentic-QA 的产物统一写入需求工作区的 `artifacts/` 目录，并通过 `reviews/` 记录确认状态，通过 `runs/` 追踪生成过程。

### 产物类型

| 产物 | 路径 | 说明 |
|---|---|---|
| 需求分析 | `artifacts/requirement-analysis.md` | 对需求背景、业务规则、流程、风险和测试范围的结构化分析 |
| 测试用例 | `artifacts/testcases.md` | 面向评审、执行、自动化生成和知识沉淀的结构化测试用例 |
| 接口测试草稿 | `artifacts/api-test-draft.md` | 接口测试计划、断言点、数据准备或脚本草稿 |
| UI 测试草稿 | `artifacts/ui-test-draft.md` | UI 测试路径、页面对象、断言点或脚本草稿 |
| 执行报告 | `artifacts/execution-report.md` | 测试执行结果、通过率、失败项和环境信息 |
| 失败分析 | `artifacts/failure-analysis.md` | 对失败用例、日志、环境和缺陷可能性的分析 |
| Bug 草稿 | `artifacts/bug-draft.md` | 可复制到缺陷系统的 Bug 标题、步骤、实际结果和预期结果 |
| QA 报告 | `artifacts/qa-report.md` | 需求质量、测试范围、执行结论、风险和遗留问题汇总 |
| 归档索引 | `artifacts/archive-index.md` | 当前需求的输入、产物、确认状态和运行记录索引 |

### 产物元数据

AI 生成产物必须包含 Front Matter，用于标记产物类型、状态、来源和确认要求。

示例：

```yaml
---
artifact_type: testcases
status: needs_human_review
human_review_required: true
source_requirement: input/requirement.md
source_api: input/api.md
generated_by: agentic-qa-runtime
run_id: ""
created_at: ""
updated_at: ""
---
```

### 产物状态

产物状态统一使用：

```text
draft
needs_human_review
approved
needs_changes
rejected
confirmed
archived
```

| 状态 | 含义 |
|---|---|
| `draft` | 草稿生成中或尚未进入确认 |
| `needs_human_review` | 等待用户通过 Chat / Bot / CLI 确认 |
| `approved` | 已确认通过，可进入下一步 |
| `needs_changes` | 需要修订后重新确认 |
| `rejected` | 当前产物不可用，需要重新生成或废弃 |
| `confirmed` | 已完成最终确认，可作为正式测试资产 |
| `archived` | 已归档 |

## 测试用例标准

测试用例产物写入：

```text
prd/<需求ID>/artifacts/testcases.md
```

测试用例用于需求评审、回归执行、自动化生成和历史知识沉淀，必须满足 **可读、可评审、可执行、可追踪、可转换** 五个要求。

### 用例组织结构

`testcases.md` 建议使用以下结构：

```markdown
---
artifact_type: testcases
status: needs_human_review
human_review_required: true
source_requirement: input/requirement.md
source_api: input/api.md
generated_by: agentic-qa-runtime
run_id: ""
created_at: ""
updated_at: ""
---

# 测试用例

## 1. 用例范围

说明本次用例覆盖的需求范围、业务流程、角色、端、接口或页面。

## 2. 测试设计依据

说明本次用例使用的测试方法，例如等价类、边界值、场景法、状态迁移、异常测试、权限测试、接口契约测试等。

## 3. 风险与优先级说明

说明 P0/P1/P2/P3 的划分依据，以及高风险业务点。

## 4. 测试用例明细

| 用例ID | 模块 | 场景 | 标题 | 优先级 | 类型 | 前置条件 | 测试数据 | 测试步骤 | 预期结果 | 覆盖点 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|

## 5. 待确认问题

记录需求不明确、规则缺失、接口不完整、依赖外部系统等需要用户确认的问题。
```

### 用例字段说明

| 字段 | 说明 |
|---|---|
| 用例ID | 当前需求内唯一，例如 `TC-001`、`TC-002` |
| 模块 | 所属业务模块，例如登录、下单、支付、售后、会员 |
| 场景 | 业务场景或测试场景，例如正常支付、库存不足、优惠券不可用 |
| 标题 | 用一句话描述用例目标 |
| 优先级 | 使用 `P0 / P1 / P2 / P3` |
| 类型 | 功能、异常、边界、权限、兼容、接口、UI、安全、性能、回归等 |
| 前置条件 | 执行前必须满足的账号、数据、环境、配置或状态 |
| 测试数据 | 输入数据、接口参数、账号角色、商品、订单、金额、配置等 |
| 测试步骤 | 清晰描述操作步骤或接口调用步骤 |
| 预期结果 | 可观察、可断言的结果，包括页面、接口、数据库、消息、状态变化 |
| 覆盖点 | 对应需求点、规则点、风险点或接口字段 |
| 备注 | 补充说明、限制条件、待确认事项 |

### 优先级定义

| 优先级 | 定义 |
|---|---|
| P0 | 主链路、资金、权限、数据一致性、核心状态流转，失败会阻断上线 |
| P1 | 重要业务分支、关键异常流程、核心角色差异、重要配置影响 |
| P2 | 一般功能分支、提示文案、普通异常、非核心组合场景 |
| P3 | 低频场景、展示细节、兼容性补充、体验优化类验证 |

### 用例质量要求

测试用例必须满足以下要求：

- 每条用例只能验证一个清晰目标，避免多个无关断言混在一起。
- 前置条件必须说明执行所需的角色、数据、环境或业务状态。
- 测试步骤必须可执行，不能只写“验证是否正常”。
- 预期结果必须可观察、可断言，不能只写“成功”“正常”“符合预期”。
- 涉及接口、数据库、消息、缓存或任务时，应说明关键校验点。
- 涉及金额、库存、权限、状态流转时，必须覆盖正常、异常和边界场景。
- 需求信息不足时，必须写入“待确认问题”，不能编造业务规则。
- 用例必须能反向追踪到需求点、风险点或接口字段。
- AI 生成的测试用例默认是草稿，必须经过确认后才能作为正式测试资产。

## 自然语言驱动的确认机制

Agentic-QA 的确认机制不是人工手动修改文件，而是一个由自然语言触发的 **Review Gate Workflow**。

用户可以通过 AI 编辑器 Chat、飞书 Bot、微信 Bot、钉钉 Bot 或 CLI 表达确认、修改、驳回、继续执行等意图。Runtime 会通过意图识别将用户输入转换为结构化确认动作，并自动更新确认记录、运行记录和后续工作流状态。

### 确认入口

用户可以通过自然语言完成确认动作：

```text
testcases.md 通过，可以继续生成接口测试。
```

```text
需求分析通过，继续生成测试用例。
```

```text
测试用例不通过，补充支付失败、库存不足和优惠券异常场景。
```

```text
Bug 草稿确认，可以作为正式缺陷提交。
```

```text
qa-report.md 需要修改，补充遗留风险和上线建议。
```

### 确认工作流

```text
用户在 Chat / Bot / CLI 表达确认意见
  ↓
意图识别
  ↓
识别为审核 / 确认 / 修订 / 继续执行类任务
  ↓
解析目标产物
  ↓
解析确认决策
  ↓
解析修改意见或下一步动作
  ↓
工作流选择
  ↓
执行 Review Gate Workflow
  ↓
更新 reviews/*.review.yml
  ↓
写入 runs/<run-id>/events.jsonl
  ↓
触发下一步工作流或进入修订流程
```

### 确认意图类型

| 用户表达 | 识别意图 | 目标状态 | 后续动作 |
|---|---|---|---|
| “通过” / “确认” / “没问题” | `approve_artifact` | `approved` | 允许进入下一步 |
| “确认并继续” / “继续生成接口测试” | `approve_and_continue` | `approved` | 触发下游工作流 |
| “需要修改” / “补充xxx” | `request_changes` | `needs_changes` | 进入修订工作流 |
| “不通过” / “废弃” | `reject_artifact` | `rejected` | 停止复用当前产物 |
| “重新生成” | `regenerate_artifact` | `draft` | 触发重新生成流程 |
| “归档” | `archive_artifact` | `archived` | 写入归档索引 |

### 确认记录

每个需要确认的产物，都应在 `reviews/` 下生成对应确认记录。

```text
prd/<需求ID>/reviews/testcases.review.yml
```

示例：

```yaml
artifact: artifacts/testcases.md
artifact_type: testcases
status: needs_human_review
reviewer: ""
reviewed_at: null
decision: ""
comments: []
required_changes: []
approved_sections: []
rejected_sections: []
next_action: ""
source_message: ""
run_id: ""
```

### 通过并继续示例

用户输入：

```text
testcases.md 通过，可以继续生成接口测试。
```

Runtime 识别结果：

```yaml
intent: approve_and_continue
artifact: artifacts/testcases.md
decision: approved
next_action: generate_api_tests
```

更新确认记录：

```yaml
artifact: artifacts/testcases.md
artifact_type: testcases
status: approved
reviewer: "qa-owner"
reviewed_at: "2026-06-12T16:00:00+08:00"
decision: "approved"
comments:
  - "测试用例确认通过，可以继续生成接口测试。"
required_changes: []
next_action: "generate_api_tests"
source_message: "testcases.md 通过，可以继续生成接口测试。"
run_id: "<run-id>"
```

### 需要修改示例

用户输入：

```text
测试用例不通过，补充支付失败、库存不足和优惠券异常场景。
```

Runtime 识别结果：

```yaml
intent: request_changes
artifact: artifacts/testcases.md
decision: needs_changes
next_action: revise_testcases
```

更新确认记录：

```yaml
artifact: artifacts/testcases.md
artifact_type: testcases
status: needs_changes
reviewer: "qa-owner"
reviewed_at: "2026-06-12T16:00:00+08:00"
decision: "needs_changes"
comments:
  - "测试用例不通过，需要补充支付失败、库存不足和优惠券异常场景。"
required_changes:
  - "补充支付失败后的订单状态校验。"
  - "补充库存不足时的下单失败提示和库存不扣减校验。"
  - "补充优惠券过期、不可叠加、门槛不足场景。"
next_action: "revise_testcases"
source_message: "测试用例不通过，补充支付失败、库存不足和优惠券异常场景。"
run_id: "<run-id>"
```

### Review Gate 规则

Runtime 必须遵守以下门禁规则：

- 用户确认动作必须通过意图识别进入 Review Gate Workflow。
- 不要求用户手动编辑 `reviews/*.review.yml`。
- 不要求用户手动维护产物状态。
- `needs_human_review` 状态下，不允许自动进入下游正式工作流。
- `needs_changes` 状态下，只允许进入修订工作流。
- `rejected` 状态下，不允许复用当前产物。
- `approved` 状态下，可以进入下一步生成流程。
- `confirmed` 状态下，可以归档，或作为正式知识资产进入 RAG。
- 所有确认动作必须记录原始用户输入、识别意图、确认决策、确认人、确认时间、意见和下一步动作。
- Chat / Bot / CLI 中的确认语义必须落到结构化确认记录，不能只停留在对话文本里。

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

```text
testcases.md 通过，可以继续生成接口测试。
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
测试用例不通过，补充支付失败、库存不足和优惠券异常场景。
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

```bash
python -m runtime.cli review approve --prd prd/demo-requirement --artifact testcases.md --reviewer qa-owner
```

运行基础检查：

```bash
pytest
ruff check .
```

## 建设路线图

```text
工程底座
├── 配置层
├── 需求工作区
├── 运行记录
├── 产物写入
└── 确认状态管理

Runtime
├── 意图识别
├── 工作流选择
├── 工作流编排
├── 状态流转
├── 质量检查
└── Review Gate Workflow

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

用户通过自然语言表达目标，系统负责理解意图、选择工作流、调用 Agent、生成产物、执行确认门禁、记录运行过程并推动下一步测试活动。
