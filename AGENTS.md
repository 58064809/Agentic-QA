# Agent 协作与执行规范

本文件是 Agentic-QA 仓库的根级 Agent 指令。执行仓库任务时先读取本文件，再按任务读取对应代码、Workflow DSL、Prompt、Rule、Skill、Knowledge 和目标 PRD 工作区。

## 项目定位

Agentic-QA 通过统一 Runtime 把自然语言任务转换为可追踪、可审核、可恢复的 QA 工程工作流：

```text
自然语言输入
  -> 意图识别
  -> Workflow DSL 选择
  -> 上下文与 RAG
  -> QA Agent 生成
  -> 质量检查
  -> 候选产物
  -> Review Gate
  -> 确定性 promote / 修订 / 驳回
```

CLI、Chat、Bot 和 API 只是不同入口，不得实现不同产物流转。

## 事实源优先级

发生冲突时按以下顺序裁决：

1. 当前运行代码与测试。
2. `workflows/runtime/*.workflow.yml` 可执行 Workflow DSL。
3. `runtime/workspace.py` 的 artifact、review、history 和 preview 路径定义。
4. `runtime/schemas/`、`runtime/graph/state.py` 等结构化 Schema。
5. `rules/` 强约束。
6. `prompts/`、`skills/`、`knowledge/`。
7. `docs/`、`README.md`、`COMMANDS.md` 的解释性内容。

文档与代码不一致时，不能为了保留文档而增加兼容逻辑；应修正文档、Prompt、Rule 或删除旧文件。

## 最高优先级规则

1. 不跳过 Review Gate。
2. 不把未经确认的 AI 输出当作正式 QA 资产。
3. 不直接覆盖正式产物。
4. 不伪造需求、接口、规则、测试数据、执行结果或缺陷结论。
5. 不把密钥、Token、Cookie 或真实敏感数据写入仓库、Prompt、日志或产物。
6. 不把目标态描述成当前已实现能力。
7. 不保留旧路径、旧命令、旧 Workflow 文档或旧状态的兼容层。
8. 不在多个 Markdown 中重复维护同一份契约。

## 文档边界

| 文件或目录 | 唯一职责 |
|---|---|
| `README.md` | 面向用户的项目入口、当前能力、快速开始和文档导航 |
| `AGENTS.md` | Agent 执行顺序、事实源优先级和仓库级边界 |
| `COMMANDS.md` | 自然语言任务与稳定 CLI 入口 |
| `docs/architecture.md` | 当前架构与层级职责 |
| `docs/workflow-dsl.md` | 当前可执行 Workflow DSL 契约 |
| `docs/prompt-engineering.md` | Prompt 结构、版本和治理规则 |
| `docs/runtime-reliability.md` | 失败、恢复、幂等、checkpoint 和运行记录 |
| `docs/artifact-versioning.md` | 候选、正式、历史版本与 promote |
| `docs/review-gate.md` | ReviewDecision、interrupt 和状态裁决 |
| `docs/artifact-standards.md` | QA 产物类型与 Front Matter |
| `docs/testcase-standards.md` | 测试用例列、优先级和质量门 |
| `rules/` | 可执行或可校验的强约束 |
| `workflows/runtime/` | 唯一可执行 Workflow 定义 |
| `prompts/` | 每个任务唯一 Prompt 正文 |
| `skills/` | 可复用 QA 方法与操作能力 |
| `knowledge/` | RAG 知识、模板和业务资产 |

同一契约只能有一个权威文件。其他文件通过链接引用，不复制全文。

## 当前工作区契约

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
│       └── <artifact>.preview.yml/json
└── metadata.yml
```

`.runtime/runs/<run-id>/` 保存 Runtime 内部摘要、graph state、RAG trace、review events 和 checkpoint 元数据，不作为正式 QA 产物目录。

## 产物流转

```text
生成内容
  -> 质量检查
  -> 写入 runs/<run-id>/<artifact>.preview.md
  -> 写入 artifact-preview.md 索引和 runs/latest.yml
  -> Review Gate interrupt
  -> approved / needs_changes / rejected
  -> approved 后调用 promote
  -> 写入 artifacts/<artifact>.md
  -> 归档旧版本
  -> 更新 review、history index 和 metadata.yml
  -> confirmed
```

`artifact-preview.md` 只表示候选索引。多产物 run 的正文必须拆分为独立 `<artifact>.preview.md`。

## 统一状态

| 状态 | 含义 |
|---|---|
| `draft` | 草稿生成中 |
| `partial` | 只完成部分内容，不能发布 |
| `needs_human_review` | 等待 Review Gate 输入 |
| `approved` | 候选已批准，可 promote |
| `needs_changes` | 必须修订并生成新候选 |
| `rejected` | 当前候选不可用 |
| `confirmed` | promote 成功后的正式产物 |
| `archived` | 已归档 |
| `failed` | 运行失败 |
| `superseded` | 已被新版本替代 |

不得创建语义重复的状态别名。

## Agent 职责

| Agent | 职责 | 候选输出 |
|---|---|---|
| Intent Router | 识别意图、PRD、artifact 和 run | 结构化任务 |
| Workflow Orchestrator | 选择 WorkflowSpec、维护状态和 checkpoint | Runtime 运行记录 |
| Requirement Analysis Agent | 提取范围、规则、风险和待确认项 | `requirement-analysis.preview.md` |
| Testcase Design Agent | 设计可追踪、可执行、可断言的测试用例 | `testcases.preview.md` |
| API Test Generation Agent | 生成 API 测试计划、断言和脚本草稿 | `api-test-draft.preview.md` |
| UI Test Generation Agent | 生成 UI 自动化路径和脚本草稿 | `ui-test-draft.preview.md` |
| API Discovery Agent | 从脱敏网络证据生成接口发现报告 | `api-discovery-report.preview.md` |
| Report Generation Agent | 汇总已确认产物和真实执行证据 | `qa-report.preview.md` |
| Review Gate | 将用户反馈解析为 `ReviewDecision` | `reviews/*.review.yml` |
| Artifact Promoter | 确定性发布、归档和更新元数据 | `artifacts/` 与 history |

Agent 不能越权执行其他角色的确定性写操作。

## Runtime 与 RAG 约束

- Runtime 只加载当前 Workflow、Prompt、Rule、Skill 和 Knowledge 文件。
- RAG 结果必须记录来源、chunk 标识、分数或命中依据、最终使用上下文和不足告警。
- `partial`、`failed`、`needs_changes`、`rejected` 或未确认候选不得作为正式知识资产。
- required 节点失败后不得静默跳过。
- 失败、重试、降级和恢复必须进入运行记录。
- 相同幂等键已成功时应复用结果或明确记录重新执行原因。

## 测试用例输出

测试用例主表固定为：

```text
用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | 测试步骤 | 预期结果 | 断言/证据 | 待确认项
```

质量要求：

- 每条用例只验证一个清晰目标。
- 步骤可执行，预期可观察、可断言。
- 用例可追踪到需求、规则、风险或接口字段。
- 金额、库存、权限、状态、幂等和并发场景必须覆盖相应异常与边界。
- 信息不足时写待确认项，禁止编造强断言。

## 修改项目时的执行顺序

1. 读取 `AGENTS.md`、`README.md` 和任务相关代码。
2. 定位程序事实源和当前 Workflow DSL。
3. 搜索所有引用点，区分权威文件、解释文件和历史产物。
4. 删除旧契约，不增加兼容分支。
5. 修改代码、测试、Rule、Prompt 和必要文档。
6. 运行 `python scripts/validate_docs_consistency.py`。
7. 运行相关 pytest、完整 pytest 和 `ruff check .`。
8. 检查 diff 中是否仍出现旧路径、重复规范或目标态冒充当前态。

Windows 环境优先使用：

```powershell
.venv\Scripts\python.exe scripts\validate_docs_consistency.py
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
```

## 完成回执

Chat 回复遵守 `rules/agent-output-rules.md`，只给变更摘要、修改文件、验收结果、待人工确认和下一步建议。未执行的命令必须说明原因，不得用完整文件或完整 diff 代替验收结论。
