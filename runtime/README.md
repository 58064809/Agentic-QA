# Runtime MVP

当前 Runtime 处于 MVP 阶段，用于第 2 阶段 LangGraph Runtime 的后续演进。010 已接入 LangGraph `StateGraph`，011 已加入本地运行记录，012 已打通需求分析与测试用例生成链路，但仍不是生产完整 Runtime。

当前真实需求交付主线仍是 Codex-first：用户在 PyCharm Chat / Codex Chat 中直接输入自然语言命令，Codex 读取仓库声明式资产和目标 PRD 工作区生成 QA 产物。Runtime CLI 目前是辅助工具，用于文档归一化、结构校验、运行记录和未来自动化能力预留；Runtime LLM 不是当前真实需求交付依赖。

## 当前能力

- 010 使用 LangGraph `StateGraph` 编排测试用例生成最小流程。
- 011 已加入本地运行记录。
- 012 支持需求分析草稿、测试用例草稿和 MVP 连续链路。
- 012A 已将默认输出提升为评审级草稿：需求分析包含 12 个评审章节，测试用例简单需求不少于 15 条，并覆盖主流程、分支、权限、状态、边界、异常、幂等、数据一致性、兼容和回归风险。
- 012B 补强质量门：低质量 Skeleton、空待确认问题、少量示例用例、非法优先级和额外“用例类型”列不能误通过。
- 013 已接入 Microsoft MarkItDown，在 `analyze`、`generate-testcases` 和 `mvp` 的上下文加载前把 Word/PDF/TXT/HTML 等需求源文件归一化为 `requirement.md`。
- 016 已废弃 `prototype-notes.md` 输入链路；Runtime 明确不分析图片/原型图内容，只检测图片痕迹并 warning。
- LLM 默认关闭，必须通过 `--use-llm` 显式启用；该能力只作为预留能力，不作为当前主线交付入口。
- LLM 配置只从本地环境变量读取：`FREEMODEL_API_KEY`、`FREEMODEL_BASE_URL`、`FREEMODEL_MODEL`。
- LLM 调用优先使用 OpenAI-compatible `responses.create`；`chat.completions.create` fallback 默认关闭，仅在本地设置 `FREEMODEL_ENABLE_CHAT_FALLBACK=true` 时启用。
- 缺少密钥或未启用 LLM 时，Runtime 降级生成确定性评审级草稿。
- 当前不接入 LangChain ChatModel。
- 当前使用本地文件化 checkpointer 快照，写入 `.runtime/runs/<run_id>/checkpointer.pkl`。
- 默认 dry-run，不写入业务产物，但会写运行记录。
- `--approve-write` 才允许写入需求分析和测试用例草稿；该参数本身就是 Runtime 写入授权。
- Graph 已启用 checkpointer，每次运行都会带 `thread_id`。
- 当前默认不再额外暂停等待 `approve` 命令；`human_review_node` 只做写入授权状态标记。
- CLI 保留 `approve`、`reject`、`resume`，仅用于兼容旧的暂停运行。
- 运行状态、Graph state 和 checkpointer 写入 `.runtime/runs/<run_id>/`。
- writer 成功后，`metadata_update_node` 会在目标 PRD 的 `metadata.yml` 中记录 `last_runtime_run` 和 `runtime_runs`；这只表示 Runtime 已按 `--approve-write` 写入草稿，不等于业务 QA 审核通过。
- 如果目标文件已存在，默认拒绝覆盖；MVP 连续链路拒绝部分写入。
- Runtime 必须读取现有声明式资产，不允许硬编码 Prompt / Rules / Skills。
- Runtime 的写入、执行、归档动作必须经过 Human Review Gate。
- Human Review Gate 当前是状态门，不是复杂交互审批。
- 运行记录默认位于 `.runtime/runs/<run_id>/`，不应提交到 Git。

## 使用命令

真实需求交付优先使用 Chat 中的 Codex-first 命令，例如：

```text
帮我分析 prd/<需求名> 需求，按仓库规则输出需求分析。
基于 prd/<需求名> 的需求分析生成测试用例。
根据评审意见增量修订 prd/<需求名> 的需求分析和测试用例。
```

以下 Runtime 命令用于验证辅助能力或后续自动化链路，不是当前主线交付要求：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/sample-login-requirement
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
```

## 需求文档归一化

Runtime 会优先使用已有 `prd/<id>/requirement.md`，不会覆盖它。如果目标工作区没有 `requirement.md`，会按固定优先级查找并转换以下文件：

```text
requirement.docx
requirement.pdf
requirement.txt
requirement.html
requirement.htm
requirement.rtf
需求.docx
需求.pdf
需求.txt
需求.html
需求.htm
```

转换输出固定为 `prd/<id>/requirement.md`。如果多个源文件同时存在，Runtime 按优先级选择一个并在 warnings 中说明。该转换是受控输入归一化写入，不需要 `--approve-write`；QA 产物写入仍必须显式传 `--approve-write`。

如果转换后的 Markdown 存在乱码、分页符、异常断行、控制字符或连续异常空格，后续可使用轻量清洗脚本生成 `requirement.cleaned.md`。清洗只允许做格式层面的无语义变更，默认不得覆盖 `requirement.md`；不做 OCR，不处理图片，不分析原型图。

## 需求输入与图片策略

Runtime 的推荐输入由两类 Markdown 文件组成：

- `requirement.md`：需求正文，来自 MarkItDown 转换或人工整理。
- `api-doc.md`：接口说明，可选。

`analyze`、`generate-testcases` 和 `mvp` 不读取 `prd/<id>/prototype-notes.md`。即使该文件存在，也不会进入上下文、Prompt、需求分析或测试用例生成。

当前 Runtime 仍是文本链路，不调用视觉模型，也不会上传、解析或间接分析图片二进制。如果 `requirement.md` 包含 Markdown 图片引用、`.png`、`.jpg`、`.jpeg`、`media/` 或 `images/` 等图片痕迹，Runtime 会 warning，并在待确认问题中提示人工确认图片中是否存在未写入正文的字段、按钮、状态、弹窗、权限差异或交互规则。测试用例生成不得基于图片内容编造字段、按钮、页面布局或交互。

图片忽略策略见 `docs/architecture/prototype-image-analysis-plan.md`。

禁用运行记录：

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement --no-record-run
```

显式写入测试用例草稿：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement --approve-write
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/sample-login-requirement --approve-write
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --approve-write
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement --approve-write
```

带 `--approve-write` 的命令会在质量门通过后直接写入产物，不需要再执行 `approve <run_id>`。写入后的产物状态仍为 `needs_human_review`，不得继续自动生成 API/UI 脚本或归档。如果目标 `10-analysis/requirement-analysis.md` 或 `20-testcases/testcases.md` 已存在，Runtime 默认拒绝覆盖。

每次运行记录默认包含：

```text
.runtime/runs/<run_id>/run-summary.json
.runtime/runs/<run_id>/run-summary.md
.runtime/runs/<run_id>/run-state.json
.runtime/runs/<run_id>/graph-state.json
.runtime/runs/<run_id>/checkpointer.pkl
```

若需要兼容旧的暂停运行，仍可使用 `approve`、`reject`、`resume`；这些命令会追加 `review-events.jsonl`，但新运行默认不再需要这一步。

质量门会阻断以下输出：缺少 `needs_human_review`、缺少需求分析 12 个必要章节、待确认问题少于 3 个、业务规则/风险/映射为空、测试用例少于 15 条、缺少 P0、优先级不属于 `P0/P1/P2/P3`、表头新增“用例类型”、表格列数不是固定 5 列、缺少至少 4 类关键覆盖维度，或仍包含纯模板占位语。

显式启用 LLM：

```bash
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --use-llm
```

默认服务地址为 `https://api.freemodel.dev`，默认模型为 `gpt-5.5`。请只在本地环境变量中设置密钥，不要提交 `.env` 或任何密钥文件。运行记录会记录是否启用 LLM、模型、服务地址、调用次数和错误摘要，但不会记录密钥。

当前阶段不建议把 `--use-llm` 作为真实业务需求的默认交付路径。真实交付应由 Codex 读取仓库规则和 PRD 文本后生成草稿，再由人工评审确认。

## 后续方向

后续可继续增强 metadata 写回、运行记录查询和业务审核状态管理。当前最终策略是不分析图片/原型图内容；如未来重新评估视觉模型接入，必须作为新的明确授权任务处理。
