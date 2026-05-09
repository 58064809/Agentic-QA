# 任务 012：MVP 打通需求分析与测试用例生成链路

## 任务目标

当前优先级调整为：下周一前至少能基于真实 PRD 完成需求分析和测试用例生成。本任务不再优先继续打磨复杂 Runtime 基础设施，而是直接实现一个可用 MVP 链路。

目标链路：

```text
自然语言命令
  ↓
Runtime CLI / LangGraph StateGraph
  ↓
读取 PRD 工作区上下文
  ↓
生成需求分析草稿
  ↓
生成测试用例草稿
  ↓
写入 prd/<需求名>/10-analysis/requirement-analysis.md
  ↓
写入 prd/<需求名>/20-testcases/testcases.md
  ↓
标记 needs_human_review
  ↓
生成 .runtime/runs/<run_id>/ 运行记录
```

本任务目标是先能用，不是把所有生产级能力一次性做完。

## 当前背景

仓库已完成：

1. 009：Runtime 最小骨架。
2. 010：LangGraph `StateGraph` 编排。
3. 011：本地 Run Records。

用户已经验证 OpenAI-compatible API 调用可用，但当前额度有限，所以 LLM 调用必须默认关闭、显式开启、严格限次、严格记录、失败可降级。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不提交任何真实密钥，不把密钥写入任何仓库文件。
4. 密钥只能从本地环境变量读取。
5. 默认不启用 LLM，必须通过 `--use-llm` 显式开启。
6. 默认 dry-run 不写业务产物；只有 `--approve-write` 才允许写入草稿。
7. 写入的需求分析和测试用例都必须标记 `needs_human_review`。
8. 不覆盖已有人工审核内容；如果目标文件已存在，默认拒绝覆盖。
9. 不执行真实测试，不生成 API/UI 自动化脚本，不归档需求。
10. 不接 Web UI、数据库、向量库或复杂平台。
11. LLM 每次 run 默认最多调用 2 次：一次需求分析、一次测试用例生成。
12. 如果未传 `--use-llm` 或缺少本地密钥环境变量，必须降级为模板化 Skeleton 草稿，不得输出堆栈。
13. 运行记录必须记录是否启用 LLM、调用节点、模型名、服务地址、调用次数、错误摘要，但不得记录密钥。
14. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 新增 CLI 能力

本任务至少新增三个 Runtime 命令能力：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/<需求名>
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/<需求名>
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/<需求名>
```

可以保留兼容原有：

```bash
python -m runtime.cli run "帮我生成测试用例" --prd prd/<需求名>
```

但本任务必须明确支持：

1. 单独生成需求分析。
2. 单独生成测试用例。
3. 一条命令连续生成需求分析 + 测试用例。

## CLI 行为要求

### 1. 需求分析

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement
```

默认行为：

- 读取 PRD 上下文。
- 生成需求分析草稿到 RuntimeResult。
- dry-run 不写 `10-analysis/requirement-analysis.md`。
- 生成运行记录。

写入行为：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement --approve-write
```

写入：

```text
prd/<需求名>/10-analysis/requirement-analysis.md
```

### 2. 测试用例生成

```bash
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/sample-login-requirement
```

默认行为：

- 读取 PRD 上下文。
- 优先读取已存在的 `10-analysis/requirement-analysis.md`。
- 如果需求分析不存在，应给 warning，并基于 `requirement.md` 生成测试用例 Skeleton 或 LLM 草稿。
- dry-run 不写 `20-testcases/testcases.md`。
- 生成运行记录。

写入行为：

```bash
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/sample-login-requirement --approve-write
```

写入：

```text
prd/<需求名>/20-testcases/testcases.md
```

### 3. MVP 连续链路

```bash
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement
```

默认 dry-run：

- 生成需求分析草稿。
- 基于需求分析草稿生成测试用例草稿。
- 不写业务产物。
- 生成运行记录。

写入：

```bash
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --approve-write
```

写入：

```text
prd/<需求名>/10-analysis/requirement-analysis.md
prd/<需求名>/20-testcases/testcases.md
```

如果其中任一目标文件已存在：

- 默认拒绝覆盖。
- 不要部分覆盖。
- 返回明确错误。

## LLM 接入要求

### 1. 新增 OpenAI-compatible Adapter

建议新增：

```text
runtime/llm/
├── __init__.py
├── config.py
├── openai_compatible.py
└── prompt_builder.py
```

### 2. 依赖要求

更新 `pyproject.toml`：

```toml
"openai>=1.0"
```

不要新增 Anthropic SDK。

### 3. 环境变量

默认使用本地环境变量：

```text
FREEMODEL_API_KEY
FREEMODEL_BASE_URL
FREEMODEL_MODEL
```

要求：

- 密钥必须由用户本地设置。
- 服务地址默认可使用 `https://api.freemodel.dev`。
- 模型默认可使用 `gpt-5.5`。
- 不得把密钥写入运行记录。

### 4. LLM 启用方式

默认不启用 LLM。

必须显式传：

```bash
--use-llm
```

如果传了 `--use-llm` 但没有本地密钥环境变量：

- 不要崩溃。
- 返回 warning：`已请求 LLM，但未设置密钥环境变量，已降级为 Skeleton 生成。`
- 继续生成 Skeleton 草稿。

### 5. LLM 调用限制

每次 run 默认最多 2 次 LLM 调用：

1. `requirement_analysis_node`
2. `testcase_generation_node`

如果只执行 analyze，最多 1 次。
如果只执行 generate-testcases，最多 1 次。

必须在运行记录中记录：

```json
"llm": {
  "enabled": true,
  "used": true,
  "provider": "openai_compatible",
  "base_url": "https://api.freemodel.dev",
  "model": "gpt-5.5",
  "calls": 2,
  "errors": []
}
```

不得记录密钥。

## Prompt 构建要求

LLM 输入不要无脑塞全仓库。

需求分析 Prompt 应读取：

```text
prd/<需求名>/requirement.md
prd/<需求名>/api-doc.md 如果存在
rules/requirement-analysis-rules.md
skills/requirement-decomposition-skill.md
skills/business-rule-extraction-skill.md
prompts/requirement-analysis-prompt.md
```

测试用例 Prompt 应读取：

```text
prd/<需求名>/requirement.md
prd/<需求名>/10-analysis/requirement-analysis.md 如果存在
rules/testcase-rules.md
skills/test-design-skill.md
knowledge/templates/testcase-template.md
prompts/testcase-design-prompt.md
```

必须限制输入长度，例如：

```text
max_input_chars = 12000
```

超出时截断并在运行记录 warning 中说明。

## 输出格式要求

### 1. requirement-analysis.md

必须包含：

```markdown
---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
---

# 需求分析草稿

## 需求概述
## 业务规则
## 流程拆解
## 角色与权限
## 数据与状态
## 异常与边界
## 风险点
## 待确认问题
```

### 2. testcases.md

必须包含：

```markdown
---
status: needs_human_review
artifact_type: testcase_draft
human_review_required: true
---

# 测试用例草稿

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
```

用例列结构必须符合：

```text
标题｜优先级｜前置条件｜测试步骤｜预期结果
```

不需要“用例类型”。

## Runtime / Graph 设计要求

可以新增两个 Graph：

```text
runtime/graph/analysis_graph.py
runtime/graph/mvp_graph.py
```

也可以扩展当前 `langgraph_app.py`。

但必须保持节点职责清晰。

建议新增节点：

```text
requirement_analysis_generation_node
requirement_analysis_quality_check_node
requirement_analysis_writer_node
mvp_artifact_writer_node
```

要求：

- 需求分析质量检查至少检查必要章节和 `needs_human_review`。
- 测试用例质量检查继续检查表头和 `needs_human_review`。
- MVP 写入必须先检查两个目标文件是否都不存在，避免部分写入。

## Run Records 扩展要求

当前 011 已有运行记录。012 要扩展记录字段：

```json
"task_type": "analysis | testcase_generation | mvp_analysis_testcases",
"artifacts": [],
"llm": {
  "enabled": false,
  "used": false,
  "provider": "openai_compatible",
  "base_url": "https://api.freemodel.dev",
  "model": "gpt-5.5",
  "calls": 0,
  "errors": []
}
```

如果为了控制改动，可以先把这些字段放进 `RuntimeResult.extra`，但必须能在 JSON 记录中看到。

## 测试要求

新增或更新测试：

```text
tests/unit/test_runtime_mvp_generation.py
tests/unit/test_llm_adapter.py
```

至少覆盖：

1. analyze dry-run 不写文件，但生成需求分析草稿。
2. analyze `--approve-write` 写入 `10-analysis/requirement-analysis.md`。
3. generate-testcases dry-run 不写文件，但生成测试用例草稿。
4. generate-testcases `--approve-write` 写入 `20-testcases/testcases.md`。
5. mvp dry-run 同时生成两类草稿，但不写文件。
6. mvp `--approve-write` 同时写两个文件。
7. mvp 如果任一目标文件已存在，拒绝写入，且不出现部分写入。
8. 缺少密钥环境变量且 `--use-llm` 时降级 Skeleton。
9. LLM Adapter 不会把密钥写入 RuntimeResult 或 run record。
10. 测试用例表头符合 `标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果`。

测试中不要真实调用外部 API。LLM 调用必须 mock。

## 文档更新要求

更新：

```text
README.md
runtime/README.md
docs/architecture/production-agent-runtime-roadmap.md
```

说明：

1. 当前 MVP 已支持需求分析和测试用例生成。
2. LLM 默认关闭。
3. 通过 `--use-llm` 显式启用。
4. 密钥从本地环境变量读取。
5. 额度有限时建议先 dry-run、小 PRD、小输出。
6. 产物必须人工审核。

## .gitignore 要求

确认以下内容仍然忽略：

```gitignore
.venv/
.runtime/runs/
```

不要提交：

```text
.env
.env.local
任何密钥文件
.runtime/runs/
.venv/
```

如果需要，补充：

```gitignore
.env
.env.*
!.env.example
```

允许新增：

```text
.env.example
```

示例内容不得包含真实密钥。

## 验收命令

完成后尽量执行：

```bash
pip install -e .
python -m runtime.cli --help
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement --no-record-run
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/sample-login-requirement --no-record-run
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --no-record-run
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/sample-login-requirement
python scripts/run_pytest.py
pytest
ruff check .
```

如果要验证 LLM，只允许使用用户本地环境变量，不得写入仓库。

注意：

- 不要默认执行 `--approve-write` 污染 sample 产物。
- 如果验证写入，请创建临时 PRD 工作区。
- 不要提交 `.runtime/runs/`。
- 不要提交 `.venv/`。

## 不做事项

本任务不要做：

1. 不做 API 自动化脚本生成。
2. 不做 UI 自动化脚本生成。
3. 不执行 pytest 真实业务测试。
4. 不做失败分析。
5. 不做 Bug 草稿。
6. 不做 QA 报告。
7. 不归档。
8. 不做 Web UI。
9. 不做数据库。
10. 不把 LLM 设为默认开启。

## 提交要求

直接提交到 `master`。

建议 Commit message：

```text
feat: add mvp analysis and testcase generation
```

## 完成后的回复要求

必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复，只输出摘要，不粘贴完整文件或完整 diff。

完成回执必须包含：

1. 变更摘要。
2. 修改文件列表。
3. 新增 CLI 命令说明。
4. LLM 是否默认关闭。
5. `--use-llm` 启用方式。
6. 本地密钥环境变量说明。
7. dry-run 是否不写业务产物。
8. `--approve-write` 是否能写入需求分析和测试用例草稿。
9. 是否避免覆盖已有文件。
10. 是否执行了测试和校验命令。
11. 未执行命令及原因。
12. 待人工确认点。
13. 下一步建议。

## 下一步预告

012 完成并审核通过后，优先进入真实需求使用：

```text
将真实需求放入 prd/<真实需求名>/requirement.md
执行 runtime mvp dry-run
人工审核输出
必要时再 approve-write
```

后续再继续：

```text
013：Human Review Command
014：API 自动化脚本生成
015：失败分析与 QA 报告
```