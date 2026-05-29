# Agentic-QA

Agentic-QA 是一个**自然语言驱动的 QA 自动化工作空间**：输入一句自然语言命令即可启动需求分析、测试用例生成、评审和归档等 QA 作业，由 LangGraph Runtime 自动路由、执行和持久化。

Agentic-QA 的终极目标是建设生产级 Agentic QA 系统。生产级不是一开始就自研平台，而是逐步具备可路由命令、声明式 QA 工作流、可复用 Agent 角色、可追踪 PRD 产物、Human-in-the-loop 门禁、可恢复 Runtime、运行记录和真实 QA 工具接入能力。

系统支持两种使用模式：**终端 CLI**（`agentic-qa "..."`）直接使用 Runtime；**IDE Chat 集成**（PyCharm / Codex Chat）中由 AI Agent 读取仓库规则并调用 Runtime 完成 QA 任务。

**纯自然语言入口**：`agentic-qa "你的自然语言命令"` 是唯一入口。基于 LLM 语义路由自动识别意图和文档来源，内置对话循环和多轮持久会话。详见 [自然语言 CLI 设计](docs/architecture/natural-language-cli-design.md)。

核心模式：

```text
AI 生成 -> 人审核 -> AI 执行 -> 人确认 -> AI 归档
```

## 架构概览

Agentic-QA 采用分层架构：

| 层 | 职责 |
|---|------|
| CLI 入口层 (`apps/`) | `agentic-qa` 自然语言入口，接收用户命令 |
| 语义路由层 (`runtime/`) | LLM 语义路由提取意图、文档来源和操作参数 |
| 状态管理层 | Session 管理器持久化对话上下文，Checkpoint 支持中断恢复 |
| 工作流执行层 | LangGraph 编排需求分析、测试用例生成等流程 |
| 产物写入层 | 自动将产物写入 `prd/<id>/` 工作区 |
| 声明式资产层 | `prompts/`、`rules/`、`qa-methods/`、`knowledge/` 提供规范约束 |

核心原则：

```text
外层 LangGraph 固定流程，内层关键生成节点用 Agent，底层文件、执行、状态、权限全部使用确定性代码
```

边界说明：

- Agentic-QA 提供标准化上下文和产物规范。
- LangGraph 提供稳定流程编排。
- LangChain 提供模型、Prompt、结构化输出和工具封装。
- 不依赖数据库或 Web 平台；状态持久化通过文件系统和 Checkpoint 机制完成。
- 详细路线见 `docs/production-agent-runtime-roadmap.md` 和 `docs/roadmap.md`。

## 工作方式

1. 用户在终端输入自然语言命令：`agentic-qa "帮我分析登录需求并生成测试用例"`
2. LLM 语义路由解析意图（analyze / generate-testcases）和文档来源（PRD 路径或本地文件路径）
3. Session 管理器创建或恢复对话上下文
4. LangGraph 工作流按意图执行：读取需求 → 需求分析 → 测试用例生成 → 写入产物
5. 产物自动写入 `prd/<id>/` 工作区
6. 进入 REPL 等待下一轮命令，支持多轮对话
7. 用户通过 `exit` 或 `退出` 结束会话

这就是"自然语言驱动"：用户不需要记子命令、参数或路由表，只需说清楚意图，Runtime 就自动完成路由、执行和持久化。

## LLM 使用边界

- 本项目的核心资产是 QA 作业规范，不是模型网关或 Agent 平台。
- Runtime 默认启用 LLM，通过 `DEEPSEEK_API_KEY` 环境变量配置密钥。
- 密钥只从本地环境变量读取，不写入仓库文件，也不写入 `.runtime/runs/` 运行记录。
- 当前默认环境变量为 `DEEPSEEK_API_KEY`，可选设置 `DEEPSEEK_BASE_URL`。
- LLM 调用使用 OpenAI-compatible `chat.completions.create` 接口。
- 未设置密钥时，Runtime 会降级生成确定性评审级草稿，不直接失败。

## 需求文档归一化

- Runtime 已接入 Microsoft MarkItDown，所有命令会先检查目标 PRD 工作区内的需求源文件。
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

当前 Runtime 明确不分析图片/原型图内容，不接视觉模型，也不使用 `prototype-notes.md` 作为输入。所有命令只基于 `requirement.md` 和 `api-doc.md` 的文本生成草稿。

如果 `requirement.md` 出现 Markdown 图片引用、`.png`、`.jpg`、`.jpeg`、`media/` 或 `images/` 等图片痕迹，Runtime 会 warning，并在待确认问题中提示人工确认图片中是否存在未写入正文的字段、按钮、状态、弹窗、权限差异或交互规则。Runtime 不会基于图片内容编造字段、按钮、布局或交互。

图片忽略策略见 `docs/architecture/prototype-image-analysis-plan.md`。

| 目录 | 用途 |
|---|---|
| `workflows/` | 声明式 QA 工作流 |
| `agents/` | Agent 角色和职责边界 |
| `prompts/` | Prompt 模板 |
| `rules/` | 路径、命名、状态、审核和专项规则 |
| `qa-methods/` | 给 Codex 参考的 QA 专业能力说明 |
| `knowledge/` | 方法论、模板、项目规则和历史经验 |
| `prd/` | 需求工作区和产物目录 |
| `docs/` | 架构、路线图和项目说明 |
| `runtime/` | LangGraph Runtime 实现 |
| `apps/` | CLI、PyCharm 和未来 Bot 的薄入口层 |
| `core/` | Runtime 无关的核心抽象预留边界 |
| `integrations/` | 飞书、LLM Provider、导出器等外部集成 |
| `rag/` | RAG 加载、切分、检索、Embedding 适配边界 |
| `configs/` | 可提交的示例配置；本地私有配置不提交 |
| `scripts/` | 工作区创建、校验、测试执行、报告和归档脚本 |
| `tests/` | 脚本单元测试 |

本地生成内容、运行日志、向量库、私有配置和真实业务输入通过 `.gitignore` 隔离，默认不进入公开仓库。

## 报告路径约定

- AI 生成的 QA 报告草稿统一写入 `prd/<id>/80-reports/qa-report-draft.md`。
- `qa-report.md` 只表示人工确认后的正式报告，可在后续人工确认流程中生成。
- 报告草稿采用“摘要 + 产物索引”方式生成，不重复粘贴完整需求分析、完整测试用例或完整执行日志。

## 对外评审导出命名

内部主产物继续使用固定英文路径，便于脚本和 Runtime 引用：

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
- 任务文件应尽量短，避免要求在 Chat 中生成超长 Markdown。
- `python scripts/validate_docs_consistency.py` 可用于检查仓库文档结构、规则模板和关键引用是否完整。

## GitHub Actions 校验

GitHub Actions 会在 push 到 `master` 和面向 `master` 的 PR 时自动运行基础校验。当前 `CI` workflow 包含文档一致性检查、sample PRD 工作区校验、pytest wrapper、pytest 和 ruff。

CI 不访问真实业务环境，不连接生产服务，也不依赖 secret。

## 快速开始

### 纯自然语言入口

```bash
agentic-qa "帮我分析登录需求 D:\需求\登录.md"
agentic-qa "帮我分析 prd/sample-login-requirement 并生成测试用例"
# 首次执行后自动进入对话模式
> 再补充几个边界用例
> 退出
```

需先设置 LLM 密钥（复制 `.env.example` 为 `.env`，或手动设置环境变量）：

```bash
set DEEPSEEK_API_KEY=your-key    # Cmd
$env:DEEPSEEK_API_KEY="your-key" # PowerShell
```

### 开发辅助脚本

真实需求日常交付优先使用 PyCharm Chat / Codex Chat 自然语言命令。下面的命令用于创建样例、校验仓库、运行脚本或验证 Runtime 辅助能力。

```bash
pip install -e .
python scripts/create_prd_workspace.py demo-requirement
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/demo-requirement
python scripts/run_pytest.py
python scripts/generate_markdown_report.py prd/sample-login-requirement
pytest
ruff check .
```

详细架构说明见 [Runtime 架构文档](runtime/README.md) 和 [自然语言 CLI 设计](docs/architecture/natural-language-cli-design.md)。

## 完整示例流程

以 `prd/sample-login-requirement` 为例，Runtime 自动识别意图并执行对应操作：

- "帮我分析登录需求" → 输出 `10-analysis/requirement-analysis.md`
- "生成测试用例" → 输出 `20-testcases/testcases.md`
- "生成接口测试脚本" → 输出 `30-api-tests/generated/test_login_api.py`
- "执行测试" → 输出 `50-execution-results/execution-report.md`
- "分析失败" → 输出 `60-failure-analysis/failure-analysis.md`
- "生成 QA 报告" → 输出 `80-reports/qa-report-draft.md`
- "确认审核后归档" → 生成归档索引

示例产物均为 AI 草稿或待人工审核内容，不代表正式 QA 结论。

## 自然语言命令示例

- "分析 `sample-login-requirement` 的需求并生成需求分析草稿。"
- "基于已审核的需求分析，为 `sample-login-requirement` 生成测试用例。"
- "根据接口文档和测试用例，生成 pytest API 自动化脚本。"
- "执行 `sample-login-requirement` 的测试并收集结果。"
- "分析失败日志，区分真实缺陷、脚本问题、环境问题和需求不清。"
- "为确认的真实缺陷生成 bug 草稿。"
- "生成 QA 报告草稿，等待人工确认。"
- "确认所有审核门后，归档该需求。"

## 人工审核原则

AI 可以生成草稿、执行脚本和整理报告，但以下内容必须由人确认：

- 需求理解和业务规则是否准确。
- 测试用例覆盖是否充分。
- 自动化脚本是否允许连接真实环境或使用真实数据。
- 失败分类和缺陷结论是否成立。
- QA 报告和归档是否可以作为正式记录。


