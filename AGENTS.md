# Agent 协作与执行规范

本文件是 Agentic-QA 仓库的根级 Agent 指令，面向自动化代理、AI 编程助手、Runtime 执行器和集成入口适配器使用。

执行本仓库任务时，应先读取本文件，再按任务类型读取 `README.md`、`docs/`、`rules/`、`workflows/`、`prompts/`、`skills/`、`knowledge/` 和目标 `prd/<需求ID>/` 工作区。

## 项目定位

Agentic-QA 是面向测试工程师的 Agentic QA Engineering 项目。用户通过 AI Chat、Bot、CLI 或 API 输入自然语言任务，Runtime 统一完成意图识别、工作流选择、上下文构建、Agent 执行、质量检查、确认门禁、产物写入和运行记录。

入口形态可以不同，但执行语义必须统一：

```text
自然语言输入
  ↓
意图识别
  ↓
工作流选择
  ↓
上下文构建
  ↓
QA Agent 执行
  ↓
质量检查
  ↓
候选产物
  ↓
Review Gate
  ↓
正式发布 / 修订 / 等待确认
```

CLI 只是自然语言入口之一，主要用于本地调试、脚本化执行和最小 Runtime 验证，不代表项目以 CLI 为中心。

## 最高优先级规则

1. 不跳过人工确认门禁。
2. 不把未经确认的 AI 输出当作正式 QA 资产。
3. 不直接覆盖正式产物。修订必须先生成候选版本，再经过质量检查和 Review Gate。
4. 不伪造需求、接口、业务规则、测试数据、执行结果或缺陷结论。
5. 不在需求工作区之外散落 QA 产物。
6. 不把密钥、Token、Cookie、真实敏感数据写入仓库、Prompt、日志、运行记录或产物。
7. 不把目标态能力描述为当前已完整实现，除非已有代码和测试验证。
8. 不把长篇内部执行契约塞回根 README；应拆入 `docs/`、`rules/`、`workflows/` 等目录。

## 文档边界

| 文件或目录 | 用途 |
|---|---|
| `README.md` | 面向人类用户的项目入口、主链路、快速开始和文档索引 |
| `AGENTS.md` | 面向 Agent 的协作规范、执行约束和仓库边界 |
| `docs/workflow-dsl.md` | Workflow DSL、节点类型、契约和路由条件 |
| `docs/runtime-reliability.md` | 失败处理、部分成功、原子写入、幂等和运行尝试 |
| `docs/artifact-versioning.md` | 候选版本、正式版本、历史索引和发布策略 |
| `docs/review-gate.md` | 自然语言确认机制和 Review Gate Workflow |
| `docs/artifact-standards.md` | QA 产物类型、Front Matter 和状态定义 |
| `docs/testcase-standards.md` | 测试用例结构、字段、优先级和质量要求 |
| `docs/rag-design.md` | RAG 链路、召回来源、上下文构建和追踪 |
| `docs/roadmap.md` | 当前建设路线图 |
| `rules/` | 路径、输出、确认门禁、版本策略和质量强约束 |
| `workflows/` | QA 工作流定义、流程配置和执行策略 |
| `prompts/` | Prompt 模板 |
| `skills/` | 可复用 QA 技能和测试方法 |
| `knowledge/` | RAG 知识库、模板和历史经验 |
| `runtime/` | Runtime 主体代码 |
| `scripts/` | 校验、创建工作区、报告和归档辅助脚本 |

历史遗留文档如与当前 README 和 `docs/` 体系冲突，应优先删除重建或改造成当前设计文档，不应继续引用过时路径或过时运行模式。

## 当前需求工作区规范

每个需求使用独立工作区：

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
├── reviews/
├── runs/
└── metadata.yml
```

关键约束：

- `input/` 保存需求原文、接口文档和附件。
- `prd/<需求ID>/runs/` 保存候选产物、latest 指针和需求级运行索引。
- `.runtime/runs/` 保存 Runtime 内部执行记录、graph state、RAG trace、review events 和恢复数据。
- `artifacts/` 只保存当前正式产物。
- `artifacts/history/` 保存历史版本和版本索引。
- `reviews/` 保存结构化确认记录。
- `metadata.yml` 保存需求级元数据、当前版本、最新运行和产物状态。

## 产物发布规则

正式产物不得由 Agent 直接覆盖。正确链路是：

```text
生成输出
  ↓
写入 runs/<run-id>/artifact-preview.md
  ↓
生成 runs/<run-id>/diff.md
  ↓
质量检查
  ↓
创建或更新 reviews/*.review.yml
  ↓
等待用户自然语言确认
  ↓
approved / confirmed
  ↓
promote_artifacts
  ↓
写入 artifacts/ 当前正式产物
  ↓
旧版本进入 artifacts/history/
  ↓
更新 history/index.yml 与 metadata.yml
```

`needs_human_review` 只能进入 `waiting_review`，不能进入 `end`。只有 `approved` 或 `confirmed` 才能进入正式发布。

## 产物状态

统一使用以下状态：

| 状态 | 含义 |
|---|---|
| `draft` | 草稿生成中或尚未进入确认 |
| `partial` | 只生成部分内容，不能作为正式产物 |
| `needs_human_review` | 等待用户通过 Chat / Bot / CLI / API 确认 |
| `approved` | 已确认通过，可进入下一步 |
| `needs_changes` | 需要修订后重新确认 |
| `rejected` | 当前产物不可用，需要重新生成或废弃 |
| `confirmed` | 已完成最终确认，可作为正式测试资产 |
| `archived` | 已归档 |
| `failed` | 生成失败，仅保留错误上下文和中间结果 |
| `superseded` | 已被新版本产物替代 |

## Agent 职责边界

| Agent | 职责 | 默认候选输出 |
|---|---|---|
| Intent Router | 识别自然语言意图、需求来源和目标产物 | 路由结果、结构化任务 |
| Workflow Orchestrator | 选择并执行工作流、维护状态和路由 | `.runtime/runs/<run-id>/run-state.json` |
| Requirement Analysis Agent | 拆解需求、识别业务规则、风险和测试范围 | `runs/<run-id>/artifact-preview.md` 中的需求分析部分 |
| Testcase Design Agent | 生成结构化测试用例、覆盖主链路、异常、边界和风险 | `runs/<run-id>/artifact-preview.md` 中的测试用例部分 |
| API Test Generation Agent | 生成接口测试计划、断言点和脚本草稿 | `artifacts/api-test-draft.md` 候选内容 |
| UI Test Generation Agent | 生成 UI 测试路径、页面对象和脚本草稿 | `artifacts/ui-test-draft.md` 候选内容 |
| Test Execution Agent | 执行测试命令并收集结果 | `artifacts/execution-report.md` 候选内容 |
| Failure Analysis Agent | 分析失败证据、区分环境、数据、脚本、产品问题 | `artifacts/failure-analysis.md` 候选内容 |
| Bug Draft Agent | 生成可复制到缺陷系统的 Bug 草稿 | `artifacts/bug-draft.md` 候选内容 |
| Report Generation Agent | 汇总 QA 报告、风险和上线建议 | `artifacts/qa-report.md` 候选内容 |
| Review Gate Agent | 解析用户确认、修改、驳回、继续执行等自然语言反馈 | `reviews/*.review.yml` |
| Archive Agent | 归档前校验确认状态、版本和索引 | `artifacts/archive-index.md` |

## Runtime 执行约束

- Runtime 应读取 `workflows/`、`prompts/`、`rules/`、`skills/`、`knowledge/`，而不是替代这些目录。
- RAG 召回结果必须可追踪，至少保留来源、chunk 标识、命中依据或分数、参与生成的上下文和不足告警。
- RAG 不应使用 `partial`、`failed` 或未确认候选产物作为正式上下文。
- 节点失败必须按照 `failure_policy` 处理，不得静默吞掉关键节点失败。
- `required: true` 节点失败后不得跳过。
- `required: false` 节点可以降级、跳过或兜底，但必须记录事件。
- 部分成功必须保留在运行记录或候选产物路径中，不得写入正式产物。
- 相同输入、相同工作流、相同 `idempotency_key` 已成功时，应复用已有运行结果或明确记录重复执行原因。

## 人工确认规则

用户可以通过自然语言表达确认动作，例如：

```text
testcases.md 通过，可以继续生成接口测试。
```

```text
测试用例不通过，补充支付失败、库存不足和优惠券异常场景。
```

Agent 必须把自然语言确认转换为结构化记录：

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

确认规则：

- 不要求用户手动编辑 `reviews/*.review.yml`。
- `needs_human_review` 状态下，不允许自动进入下游正式工作流。
- `needs_changes` 状态下，只允许进入修订工作流。
- `rejected` 状态下，不允许复用当前产物。
- `approved` 状态下，可以进入下一步生成流程。
- `confirmed` 状态下，可以归档，或作为正式知识资产进入 RAG。

## 测试用例输出要求

测试用例默认输出为 Markdown 大表，字段固定：

```text
用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | 测试步骤 | 预期结果 | 断言/证据 | 待确认项
```

质量要求：

- 每条用例只验证一个清晰目标。
- 前置条件必须说明角色、数据、环境或业务状态。
- 测试步骤必须可执行。
- 预期结果必须可观察、可断言。
- 涉及接口、数据库、消息、缓存或任务时，应说明关键校验点。
- 涉及金额、库存、权限、状态流转时，必须覆盖正常、异常和边界场景。
- 信息不足时必须写入待确认问题，不得编造业务规则。
- 用例必须能反向追踪到需求点、风险点或接口字段。

## 默认回复格式

Agent 完成任务后的 Chat 回复应简洁，遵循 `rules/agent-output-rules.md` 的完成回执要求。默认包含：

```text
变更摘要
修改文件
验收结果
待人工确认
下一步建议
```

不得把完整文件内容粘贴到 Chat 中代替路径、摘要和验收结果。

## 常用工程命令

```bash
python scripts/create_prd_workspace.py demo-requirement
python scripts/validate_prd_workspace.py prd/demo-requirement
python scripts/validate_docs_consistency.py
python -m runtime.cli "分析 prd/demo-requirement 并生成测试用例"
pytest
ruff check .
```

## 修改项目时的执行顺序

1. 读取 `AGENTS.md`。
2. 读取 `README.md` 理解项目入口和当前主链路。
3. 按任务读取对应 `docs/*.md`。
4. 检查相关 `rules/`、`workflows/`、`prompts/`、`skills/`、`knowledge/`。
5. 修改代码或文档。
6. 同步更新测试、校验脚本和文档索引。
7. 能运行则运行相关测试；不能运行必须说明原因。
8. 回复时只给摘要、文件路径、验证结果和待确认项。
