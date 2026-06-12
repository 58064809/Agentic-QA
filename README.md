# Agentic-QA

Agentic-QA 是一个面向测试工程师的 **Runtime-first Agentic QA System**。

它的目标不是只提供一组给 Codex/ChatGPT 阅读的文档规范，而是建设一套可以在本地运行、可编排、可追踪、可扩展的 Agentic QA Runtime：输入需求文档，经过文档归一化、RAG 检索、Agent 编排、测试方法论推理、人工审核门禁，最终生成需求分析、测试用例、自动化脚本草稿、执行结果、失败分析、Bug 草稿、QA 报告和归档资产。

核心模式：

```text
需求输入 -> 文档归一化 -> RAG 检索 -> Agent 工作流 -> 产物生成 -> 人工审核 -> 修订/执行/归档
```

## 当前定位

Agentic-QA 从现在开始按 **Runtime-first** 方向改造。

这意味着：

- Runtime 是项目主入口，不再只是辅助能力。
- 仓库中的 `runtime/`、`knowledge/`、`prompts/`、`rules/`、`skills/`、`workflows/`、`prd/` 将共同组成可执行系统。
- ChatGPT 项目「来源」数据可以删除，项目上下文必须沉淀回仓库本身。
- Codex / Cursor / ChatGPT / Claude Code 仍可用于开发和辅助，但不再作为唯一执行大脑。
- 最终目标是让用户通过 CLI 或后续 Bot/API 触发 Runtime 自动完成 QA 工作流。

## 核心目标

Agentic-QA 要解决的问题是：

1. 测试工程师拿到 PRD 后，如何快速完成高质量需求分析。
2. 如何基于测试方法论和历史知识生成结构化测试用例。
3. 如何把知识库、规则、Prompt、Skills 和需求上下文稳定注入生成链路。
4. 如何让每次生成都有可追踪输入、召回依据、输出路径和人工审核状态。
5. 如何逐步从需求分析/用例生成扩展到接口脚本、UI 脚本、执行、失败分析、Bug 草稿和 QA 报告。

## Runtime 总体架构

```text
User Command / CLI / Bot
  ↓
Command Router
  ↓
Workflow Orchestrator
  ↓
Requirement Loader / Document Normalizer
  ↓
RAG Retriever
  ↓
Context Builder
  ↓
Agent Nodes
  ├── Requirement Analysis Agent
  ├── Testcase Design Agent
  ├── API Test Generation Agent
  ├── UI Test Generation Agent
  ├── Test Execution Agent
  ├── Failure Analysis Agent
  ├── Bug Draft Agent
  └── QA Report Agent
  ↓
Quality Gate
  ↓
Human Review Gate
  ↓
Artifact Writer
  ↓
Run Recorder / Metadata Updater
```

## 第一阶段 MVP

第一阶段不追求全链路自动化，先打通最核心闭环：

```text
需求文档 -> RAG -> 需求分析 -> 测试用例 -> 人工审核
```

第一阶段必须具备：

- PRD 工作区创建与校验。
- `requirement.md` / `api-doc.md` 读取。
- Word / PDF / TXT / HTML 到 Markdown 的需求归一化。
- Markdown 知识库切分。
- 基于规则或 embedding 的 RAG 检索。
- Prompt 构建与上下文预算控制。
- 需求分析 Agent。
- 测试用例 Agent。
- 输出 Markdown 产物。
- 产物状态标记为 `needs_human_review`。
- 运行记录落到 `.runtime/runs/<run_id>/`。

第一阶段不做：

- Web 平台。
- 复杂权限系统。
- 在线多用户协作。
- 真实生产环境测试执行。
- 无人工审核的全自动发布结论。

## RAG 设计原则

Agentic-QA 的 RAG 不只是把文件拼进 Prompt。

真正的 RAG 链路必须包含：

```text
Document Load -> Chunk -> Index -> Retrieve -> Rerank/Select -> Context Build -> Generate
```

知识来源包括：

| 来源 | 用途 |
|---|---|
| `prd/<id>/requirement.md` | 当前需求正文 |
| `prd/<id>/api-doc.md` | 当前需求接口文档 |
| `knowledge/` | 测试方法、领域经验、历史案例 |
| `rules/` | 强约束规则 |
| `skills/` | 可复用测试能力说明 |
| `prompts/` | 任务提示词模板 |
| `workflows/` | 工作流定义 |

RAG 输出必须可追踪，生成产物中应能看到关键召回来源或运行记录中保留检索结果。

## Human-in-the-loop 原则

AI 可以生成草稿、执行脚本、整理分析，但不能替代测试工程师做最终判断。

以下节点必须支持人工审核：

- 需求分析审核。
- 测试用例审核。
- 自动化脚本审核。
- 测试执行范围确认。
- 失败原因确认。
- Bug 是否成立确认。
- QA 报告确认。

产物状态统一使用：

```text
draft
needs_human_review
approved
needs_changes
rejected
needs_human_confirmation
confirmed
archived
```

## PRD 工作区结构

每个需求必须有独立工作区：

```text
prd/<requirement-id>/
├── requirement.md
├── api-doc.md
├── metadata.yml
├── 10-analysis/
│   └── requirement-analysis.md
├── 20-testcases/
│   └── testcases.md
├── 30-api-tests/
│   ├── api-test-plan.md
│   └── generated/
├── 40-ui-tests/
│   ├── ui-test-plan.md
│   └── generated/
├── 50-execution-results/
│   ├── pytest-result.json
│   └── execution-report.md
├── 60-failure-analysis/
│   └── failure-analysis.md
├── 70-bugs/
│   └── bug-draft.md
├── 80-reports/
│   └── qa-report.md
└── 90-archive/
    └── archive-index.md
```

## 目录说明

| 路径 | 职责 |
|---|---|
| `runtime/` | Agentic QA Runtime 主体代码 |
| `runtime/graph/` | 工作流编排、状态流转、节点定义 |
| `runtime/rag/` | 文档切分、索引、检索、上下文选择 |
| `runtime/llm/` | LLM Provider 抽象和模型调用适配 |
| `runtime/tools/` | 文件读取、产物写入、测试执行、报告生成等确定性工具 |
| `runtime/schemas/` | Pydantic Schema 和结构化输入输出定义 |
| `workflows/` | 声明式工作流定义 |
| `agents/` | Agent 角色、职责、输入输出和约束 |
| `tasks/` | 任务 SOP |
| `prompts/` | Prompt 模板 |
| `rules/` | 强约束规则 |
| `skills/` | 测试专业能力说明 |
| `knowledge/` | RAG 知识库 |
| `prd/` | 需求工作区和生成产物 |
| `scripts/` | 工程辅助脚本 |
| `tests/` | 单元测试和 Runtime 测试 |
| `docs/` | 架构设计、路线图、使用说明 |

## 快速开始

安装本地开发包：

```bash
pip install -e .
```

创建需求工作区：

```bash
python scripts/create_prd_workspace.py demo-requirement
```

校验仓库文档和需求工作区：

```bash
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/demo-requirement
```

运行 Runtime MVP：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/demo-requirement
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/demo-requirement
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/demo-requirement
```

确认写入产物：

```bash
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/demo-requirement --confirm
```

运行基础质量检查：

```bash
pytest
ruff check .
```

## LLM 配置

Runtime 不在仓库中保存任何密钥。

默认通过本地环境变量读取 OpenAI-compatible 配置：

```bash
FREEMODEL_API_KEY=your-local-key
FREEMODEL_BASE_URL=https://api.example.com/v1
FREEMODEL_MODEL=your-model-name
```

是否启用 LLM 必须由命令显式控制。未配置密钥时，Runtime 不应把密钥写入运行记录、日志或产物。

## 产物要求

需求分析输出：

```text
prd/<id>/10-analysis/requirement-analysis.md
```

测试用例输出：

```text
prd/<id>/20-testcases/testcases.md
```

测试用例表格固定使用：

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|

优先级统一使用：

```text
P0 / P1 / P2 / P3
```

所有 AI 生成产物默认必须标记为：

```yaml
status: needs_human_review
human_review_required: true
```

## 项目边界

Agentic-QA 当前要做：

- Runtime 编排。
- RAG 检索。
- QA Agent 工作流。
- 需求分析生成。
- 测试用例生成。
- 产物状态管理。
- 人工审核门禁。
- 运行记录。
- 可扩展到自动化脚本、执行、失败分析和报告。

Agentic-QA 当前不做：

- 完整测试管理平台。
- Web 多用户系统。
- 替代人工 QA 决策。
- 直接连接生产环境执行测试。
- 在仓库中保存真实业务密钥或敏感数据。

## 后续路线

```text
阶段 1：Runtime MVP + RAG + 需求分析 + 测试用例
阶段 2：接口测试脚本生成 + pytest 执行 + 失败分析
阶段 3：UI 测试脚本生成 + Playwright 执行
阶段 4：QA 报告 + 归档 + 历史知识沉淀
阶段 5：Bot/API/Web UI 接入
```

## 一句话总结

Agentic-QA 要从“让 AI 读仓库规则生成 QA 草稿”的工作台，升级为“由 Runtime 编排、RAG 增强、Agent 协作、人类审核”的可执行 Agentic QA 系统。
