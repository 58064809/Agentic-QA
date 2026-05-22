# Agentic-QA

Agentic-QA 是一个**指令路由型人机协同 Agentic QA 工作空间**：用自然语言命令驱动 Codex 执行 QA 作业，用文件化规范约束输入、输出、审核门和归档路径。

Agentic-QA 的终极目标是建设生产级 Agentic QA 系统。生产级不是一开始就自研平台，而是逐步具备可路由命令、声明式 QA 工作流、可复用 Agent 角色、可追踪 PRD 产物、Human-in-the-loop 门禁、可恢复 Runtime、运行记录和真实 QA 工具接入能力。

当前真实需求交付主线是 Codex-first：在 PyCharm Chat / Codex Chat 中直接输入自然语言命令，由 Codex 读取仓库规则和目标 PRD 工作区，生成需求分析、测试用例和评审草稿。当前阶段不依赖 `python -m runtime.cli ... --use-llm`，也不把 Runtime LLM 作为真实需求交付前置。

当前阶段不实现完整 Agent Runtime、数据库或 Web 平台，而是用 `COMMANDS.md`、`workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/` 和 `prd/` 固定 Codex / ChatGPT / IDE Agent 的执行行为。第 2 阶段已开始引入轻量 LangGraph Runtime；Runtime CLI 目前定位为文档归一化、结构校验、运行记录和未来自动化预留。Runtime 默认不启用 LLM，仅在用户显式传入 `--use-llm` 且本地环境变量已配置时，使用 OpenAI-compatible adapter 生成草稿。

核心模式：

```text
AI 生成 -> 人审核 -> AI 执行 -> 人确认 -> AI 归档
```

## 两阶段路线

### 第 1 阶段：Codex 驱动的标准化工作台

第 1 阶段继续把 Agentic-QA 做成标准化 QA 工作台，由 Codex / ChatGPT / IDE Agent 读取仓库规则完成 QA 任务。核心资产仍然是 `AGENTS.md`、`COMMANDS.md`、`workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/`、`prd/`、`scripts/` 和 `tests/`。

当前推荐的真实需求链路是：

```text
PDF/Word/TXT/HTML -> requirement.md
Codex 读取 requirement.md / api-doc.md / 仓库规则
Codex 生成需求分析和测试用例
人工评审确认
Codex 按评审意见增量修订
必要时导出中文命名评审文件
```

日常命令示例：

```text
帮我分析 prd/<需求名> 需求，按仓库规则输出需求分析。
基于 prd/<需求名> 的需求分析生成测试用例。
根据评审意见增量修订 prd/<需求名> 的需求分析和测试用例。
将 prd/<需求名> 的产物导出为中文评审文件。
```

### 第 2 阶段：LangGraph Runtime 驱动的轻量执行引擎

第 2 阶段新增轻量 Runtime，用 LangGraph 承接流程、状态、条件路由、循环修正、Human-in-the-loop、持久化和运行记录，用 LangChain 承接模型调用、Prompt 模板、结构化输入输出和工具封装。

核心原则：

```text
外层 LangGraph 固定流程，内层关键生成节点用 Agent，底层文件、执行、状态、权限全部使用确定性代码
```

边界说明：

- Agentic-QA 提供标准化上下文和产物规范。
- LangGraph 提供稳定流程编排。
- LangChain 提供模型、Prompt、结构化输出和工具封装。
- Codex 继续负责代码开发和人工协作施工。
- 不要一开始就重写成 Runtime，必须先保留并复用声明式资产。
- 详细路线见 `docs/architecture/production-agent-runtime-roadmap.md` 和 `docs/roadmap.md`。

## 工作方式

1. 人用自然语言命令说明要做的 QA 动作，例如“分析 `prd/sample-login-requirement` 并生成测试用例”。
2. Codex 读取 `COMMANDS.md`，路由到对应 `tasks/`、`workflows/`、`agents/`、`prompts/`、`rules/`、`skills/` 和 `knowledge/`。
3. Codex 只在 PRD 工作区内生成产物，并把状态标记为待审核或待确认。
4. 人审核分析、用例、脚本、结果、缺陷和报告。
5. 全部审核通过后，Codex 执行归档脚本生成归档索引。

这就是“指令路由型”：用户不需要调用某个内置平台或 Runtime，只要描述意图，Codex 就按路由表找到声明式文件链路并生成对应产物。

## LLM 使用边界

- 本项目的核心资产是 QA 作业规范，不是模型网关或 Agent 平台。
- Runtime MVP 提供轻量 OpenAI-compatible adapter，但默认关闭，必须通过 `--use-llm` 显式启用；该能力是预留能力，不是当前真实需求交付依赖。
- 密钥只从本地环境变量读取，不写入仓库文件，也不写入 `.runtime/runs/` 运行记录。
- 当前默认环境变量为 `FREEMODEL_API_KEY`、`FREEMODEL_BASE_URL`、`FREEMODEL_MODEL`。
- LLM 调用优先使用 OpenAI-compatible `responses.create`；`chat.completions.create` fallback 默认关闭，仅在本地设置 `FREEMODEL_ENABLE_CHAT_FALLBACK=true` 时启用。
- 未启用 LLM 或缺少密钥时，Runtime 会降级生成确定性评审级草稿，不直接失败。

## 需求文档归一化

- Runtime MVP 已接入 Microsoft MarkItDown，`analyze`、`generate-testcases` 和 `mvp` 会先检查目标 PRD 工作区内的需求源文件。
- 如果 `prd/<id>/requirement.md` 已存在，Runtime 直接使用它，不转换也不覆盖。
- 如果没有 `requirement.md`，Runtime 会按固定优先级查找 `requirement.docx`、`requirement.pdf`、`requirement.txt`、`requirement.html`、`requirement.htm`、`requirement.rtf`，以及 `需求.docx`、`需求.pdf`、`需求.txt`、`需求.html`、`需求.htm`。
- 找到受支持源文件后，Runtime 会将其转换为 `prd/<id>/requirement.md`，再继续需求分析和测试用例生成。
- 不做目录递归扫描或批量导入，不提交真实业务 Word/PDF 文件；原始需求应只放在目标 PRD 工作区内。

Markdown 轻量清洗策略：

- MarkItDown 是当前默认文档转 Markdown 工具。
- 如果转换后的 `requirement.md` 存在乱码、分页符、异常断行、控制字符或连续异常空格，可使用后续轻量清洗脚本生成 `requirement.cleaned.md`。
- 清洗只允许去除控制字符、规范空行、清理明显分页符和修复连续异常空格，不得修改业务语义。
- 默认不得覆盖 `requirement.md`；需要覆盖时必须由用户显式确认。
- 不做 OCR，不处理图片，不分析原型图；扫描件识别、Pandoc 或 Poppler/pdftotext 接入都属于后续明确授权任务。

## 需求输入与图片策略

- `requirement.md`：需求正文，来自 MarkItDown 转换或人工整理。
- `api-doc.md`：接口说明，可选。

当前 Runtime 明确不分析图片/原型图内容，不接视觉模型，也不使用 `prototype-notes.md` 作为输入。`analyze`、`generate-testcases` 和 `mvp` 只基于 `requirement.md` 和 `api-doc.md` 的文本生成草稿。

如果 `requirement.md` 出现 Markdown 图片引用、`.png`、`.jpg`、`.jpeg`、`media/` 或 `images/` 等图片痕迹，Runtime 会 warning，并在待确认问题中提示人工确认图片中是否存在未写入正文的字段、按钮、状态、弹窗、权限差异或交互规则。Runtime 不会基于图片内容编造字段、按钮、布局或交互。

图片忽略策略见 `docs/architecture/prototype-image-analysis-plan.md`。

## 目录说明

| 目录 | 用途 |
|---|---|
| `workflows/` | 声明式 QA 工作流 |
| `agents/` | Agent 角色和职责边界 |
| `tasks/` | 可执行 SOP |
| `prompts/` | Prompt 模板 |
| `rules/` | 路径、命名、状态、审核和专项规则 |
| `skills/` | 给 Codex 参考的 QA 专业能力说明 |
| `knowledge/` | 方法论、模板、项目规则和历史经验 |
| `prd/` | 需求工作区和产物目录 |
| `docs/` | 架构、路线图和项目说明 |
| `scripts/` | 工作区创建、校验、测试执行、报告和归档脚本 |
| `tests/` | 脚本单元测试 |

## 报告路径约定

- AI 生成的 QA 报告草稿统一写入 `prd/<id>/80-reports/qa-report-draft.md`。
- `qa-report.md` 只表示人工确认后的正式报告，可在后续人工确认流程中生成。
- 报告草稿采用“摘要 + 产物索引”方式生成，不重复粘贴完整需求分析、完整测试用例或完整执行日志。

## 对外评审导出命名

内部主产物继续使用固定英文路径，便于脚本和 Codex 路由：

```text
10-analysis/requirement-analysis.md
20-testcases/testcases.md
80-reports/qa-report-draft.md
```

需要发给产品、领导或外部评审时，可以在目标 PRD 工作区下新增中文命名导出文件：

```text
exports/<需求标题>-需求分析.md
exports/<需求标题>-测试用例.md
exports/<需求标题>-QA评审摘要.md
```

导出文件不得替代内部主文件；主文件评审通过后如需重生成对比版，应使用 `*-v2.md` 或复制新的 PRD 工作区。

## Codex 输出约定

- 为减少浏览器卡顿，Codex 完成任务后只在 Chat 中输出摘要、关键文件路径、验收结果和待人工确认项。
- 大段 Markdown、长报告、完整 diff 和批量产物必须写入仓库文件，通过路径查看。
- 审核时优先打开对应文件路径，不要求 Codex 在 Chat 中重复粘贴完整内容。
- Codex 完成任务后应使用统一完成回执，人工审核时优先看“修改文件”和“验收结果”。
- 未执行的验收命令不能视为通过，必须在回执中写明原因。
- 后续 `_codex_tasks/` 任务文件应尽量短，避免要求在 Chat 中生成超长 Markdown。
- `python scripts/validate_docs_consistency.py` 可用于检查仓库文档结构、规则模板和关键引用是否完整。

## GitHub Actions 校验

GitHub Actions 会在 push 到 `master` 和面向 `master` 的 PR 时自动运行基础校验。当前 `CI` workflow 包含文档一致性检查、sample PRD 工作区校验、pytest wrapper、pytest 和 ruff。

CI 不访问真实业务环境，不连接生产服务，也不依赖 secret。

## 快速开始

真实需求日常交付优先使用 PyCharm Chat / Codex Chat 自然语言命令。下面的命令用于创建样例、校验仓库、运行脚本或验证 Runtime 辅助能力。

```bash
pip install -e .
python scripts/create_prd_workspace.py demo-requirement
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/demo-requirement
python scripts/run_pytest.py
python scripts/generate_markdown_report.py prd/sample-login-requirement
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement --no-record-run
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/sample-login-requirement --no-record-run
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --no-record-run
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement --no-record-run
pytest
ruff check .
```

## Runtime MVP

第 2 阶段 Runtime 已使用 LangGraph `StateGraph` 编排 MVP 流程，支持需求分析草稿、测试用例草稿，以及连续生成“需求分析 + 测试用例”。012A 已将默认输出提升为评审级草稿：需求分析固定输出 12 个评审章节，测试用例固定使用 `标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果` 表头，简单需求默认满足不少于 15 条用例的质量门。Runtime 不连接真实业务环境，不执行真实测试，不生成 API/UI 自动化脚本。默认命令为 dry-run，不写入业务产物：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/sample-login-requirement
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
```

只有显式传入 `--approve-write` 才允许写入草稿。`analyze` 写入 `prd/<id>/10-analysis/requirement-analysis.md`，`generate-testcases` 写入 `prd/<id>/20-testcases/testcases.md`，`mvp` 同时写入两类草稿。若任一目标文件已存在，Runtime 默认拒绝覆盖；`mvp` 会拒绝部分写入。写入后的状态仍为 `needs_human_review`，不得继续自动生成 API/UI 脚本或归档。

Runtime Graph 已启用 checkpointer，每次运行都会带 `thread_id`。`human_review_node` 使用 LangGraph `interrupt` 暂停，审批通过后才允许 writer 节点写入：

```bash
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --approve-write
python -m runtime.cli approve <run_id> --reviewed-by user --review-notes "确认通过"
python -m runtime.cli reject <run_id> --reviewed-by user --review-notes "退回修改"
python -m runtime.cli resume <run_id>
```

Runtime 默认会在 `.runtime/runs/<run_id>/` 下生成本地运行记录，用于追踪节点轨迹、加载文件、输出路径、错误、审核状态、Graph state 和 checkpointer。运行记录不应提交到 Git；如只想执行流程而不生成记录，可传入 `--no-record-run`。

MVP 质量门会检查需求分析是否包含 `needs_human_review`、12 个必要章节、至少 3 个具体待确认问题、实质业务规则、风险点与影响面、需求到测试覆盖映射；测试用例会检查固定 5 列表头、至少 15 条非表头用例、P0 用例、合法优先级、至少 4 类关键覆盖场景，并拒绝 Skeleton 占位语和“用例类型”等额外列。

LLM 默认关闭。显式传入 `--use-llm` 后，Runtime 从本地环境变量读取配置：

```bash
FREEMODEL_API_KEY=your-local-key
FREEMODEL_BASE_URL=https://api.freemodel.dev
FREEMODEL_MODEL=gpt-5.5
```

如果额度有限，建议先使用 dry-run、小 PRD 和小输出验证；所有产物仍必须人工审核。

## 完整示例流程

以 `prd/sample-login-requirement` 为例：

1. “请分析登录需求”会路由到 `workflows/01-requirement-analysis-workflow.md`，输出 `10-analysis/requirement-analysis.md`。
2. “请生成测试用例”会路由到 `workflows/02-testcase-generation-workflow.md`，输出 `20-testcases/testcases.md`。
3. “请生成接口测试脚本”会路由到 `workflows/03-api-test-generation-workflow.md`，输出 `30-api-tests/api-test-plan.md` 和 `30-api-tests/generated/test_login_api.py`。
4. “请执行测试”会路由到 `workflows/05-test-execution-workflow.md`，输出 `50-execution-results/execution-report.md`。
5. “请分析失败”会路由到 `workflows/06-failure-analysis-workflow.md`，输出 `60-failure-analysis/failure-analysis.md`。
6. “请生成 QA 报告”会路由到 `workflows/08-report-generation-workflow.md`，输出 `80-reports/qa-report-draft.md`。
7. “请归档”会路由到 `workflows/09-archive-workflow.md`，仅在审核门通过后生成 `90-archive/archive-index.md`。

示例产物均为 AI 草稿或待人工审核内容，不代表正式 QA 结论。

## 自然语言命令示例

- “定位 `sample-login-requirement`，读取需求、接口文档和 metadata，生成需求分析草稿。”
- “基于已审核的需求分析，为 `sample-login-requirement` 生成测试用例。”
- “根据接口文档和测试用例，生成 pytest API 自动化脚本草稿。”
- “执行 `sample-login-requirement` 的测试并收集结果。”
- “分析失败日志，区分真实缺陷、脚本问题、环境问题和需求不清。”
- “为确认的真实缺陷生成 bug 草稿。”
- “生成 QA 报告草稿，等待人工确认。”
- “确认所有 review gate 后，归档该需求。”

## 人工审核原则

AI 可以生成草稿、执行脚本和整理报告，但以下内容必须由人确认：

- 需求理解和业务规则是否准确。
- 测试用例覆盖是否充分。
- 自动化脚本是否允许连接真实环境或使用真实数据。
- 失败分类和缺陷结论是否成立。
- QA 报告和归档是否可以作为正式记录。

## 临时任务目录

`_codex_tasks/` 是施工任务目录，仅用于驱动 Codex 分阶段建设本仓库。项目正式使用说明以根目录 `README.md`、`COMMANDS.md` 和各规范目录为准；建设完成后，`_codex_tasks/` 可删除或归档。
