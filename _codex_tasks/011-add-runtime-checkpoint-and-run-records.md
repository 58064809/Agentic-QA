# 任务 011：新增 Runtime 运行记录与轻量可追踪能力

## 任务目标

在 009 已新增 Runtime 骨架、010 已接入 LangGraph `StateGraph` 后，本任务继续增强第 2 阶段 Runtime 的生产级基础能力：新增**轻量运行记录 Run Records**。

本任务不是完整持久化系统，也不是数据库方案。011 只做本地文件型运行记录，用于让每次 Runtime 执行可追踪、可审计、可复查，为后续 Checkpoint / Resume / Human-in-the-loop 持久化打基础。

011 的目标是：

1. 每次 Runtime 执行生成唯一 `run_id`。
2. 每次执行生成本地运行记录目录。
3. 记录用户输入、PRD 路径、执行模式、编排方式、节点轨迹、加载文件列表、输出路径、错误、警告、质量检查结果和是否写入文件。
4. dry-run 也要记录运行结果，但不得写业务产物。
5. `--approve-write` 写入测试用例草稿时，也要记录运行结果。
6. 不接数据库、不接真实业务环境、不接真实 LLM。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不引入 PostgreSQL、SQLite、Redis、向量库或 Web 平台。
4. 不接入真实 LLM，不读取 API Key，不调用 OpenAI / Anthropic / LangChain ChatModel。
5. 不执行真实业务测试，不归档需求。
6. 不覆盖已有 `testcases.md`。
7. 继续保持默认 dry-run 不写业务产物。
8. Runtime 运行记录允许写入 `.runtime/` 目录，但 `.runtime/runs/` 应加入 `.gitignore`，避免提交本地运行记录。
9. 运行记录不得保存敏感信息；当前可以保存用户输入、仓库相对路径、节点轨迹、摘要和错误信息，但不要保存环境变量、API Key、完整密钥、Cookie、Token。
10. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 背景

当前 Runtime 已具备：

```text
CLI → LangGraph StateGraph → 确定性节点 → dry-run / approve-write → RuntimeResult
```

但缺少每次执行的可追踪记录。011 要补齐轻量运行记录，为后续生产级能力打基础。

## 推荐新增目录结构

新增：

```text
runtime/records/
├── __init__.py
├── run_id.py
└── run_recorder.py
```

运行时本地输出目录：

```text
.runtime/
└── runs/
    └── <run_id>/
        ├── run-summary.json
        └── run-summary.md
```

注意：

- `.runtime/runs/` 是本地运行产物，不应提交。
- 代码目录是 `runtime/records/`，要提交。
- 如果需要保留目录，可以提交 `.runtime/.gitkeep`，但不要提交实际 run 记录。

## run_id 要求

`run_id` 建议格式：

```text
run-YYYYMMDD-HHMMSS-短随机串
```

例如：

```text
run-20260509-153012-a1b2c3
```

要求：

- 不依赖外部服务。
- 同一秒内多次运行不应冲突。
- 单元测试中可以通过注入固定时间或 monkeypatch 保证可测试。

## RuntimeResult 扩展要求

更新 `runtime/schemas/runtime_result.py`，新增字段：

```python
run_id: str | None
run_record_dir: str | None
run_summary_json: str | None
run_summary_md: str | None
```

或者字段名可以略有调整，但必须表达清楚：

- 本次运行 ID。
- 运行记录目录。
- JSON 记录路径。
- Markdown 记录路径。

同时 `runtime/cli.py` 的输出摘要里应展示：

```text
- Run ID: xxx
- 运行记录: .runtime/runs/<run_id>/run-summary.md
```

## 状态对象扩展要求

更新 `runtime/graph/state.py`，给 `QAWorkflowState` 和 `GraphQAWorkflowState` 增加：

```python
run_id: str | None
run_record_dir: str | None
run_summary_json: str | None
run_summary_md: str | None
```

并更新 `to_graph_state()` / `from_graph_state()`。

## 记录器实现要求

新增 `runtime/records/run_recorder.py`。

建议提供函数：

```python
record_runtime_result(result: RuntimeResult, repo_root: Path) -> RuntimeResult
```

或：

```python
write_run_record(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState
```

推荐记录内容：

### run-summary.json

至少包含：

```json
{
  "run_id": "run-xxx",
  "created_at": "2026-05-09T15:30:12+08:00",
  "success": true,
  "orchestration": "LangGraph StateGraph",
  "mode": "dry-run",
  "user_input": "...",
  "prd_path": "prd/sample-login-requirement",
  "intent": "testcase_generation",
  "workflow_files": [],
  "loaded_files": [],
  "executed_nodes": [],
  "output_path": "prd/.../20-testcases/testcases.md",
  "wrote_file": false,
  "review_status": "needs_human_review",
  "errors": [],
  "warnings": [],
  "quality_errors": []
}
```

注意：

- `loaded_files` 记录路径列表即可，不要把所有文件全文写入 JSON，避免运行记录过大。
- 不要保存完整 `draft_artifact`，最多保存摘要或 `draft_artifact_preview` 前 300 字。

### run-summary.md

建议内容：

```markdown
# Runtime 运行记录

## 基本信息

- Run ID：xxx
- 时间：xxx
- 模式：dry-run / approve-write
- 编排方式：LangGraph StateGraph
- PRD：prd/xxx
- 意图：testcase_generation
- 成功：true / false

## 节点轨迹

1. intent_router_node
2. workflow_selector_node
...

## 文件与产物

- 输出路径：prd/xxx/20-testcases/testcases.md
- 是否写入：否
- 加载文件：...

## 审核状态

- review_status：needs_human_review

## 错误与警告

- errors：无
- warnings：...
- quality_errors：无
```

## CLI 要求

`runtime/cli.py` 保持原有命令兼容：

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
```

新增参数：

```bash
--record-run / --no-record-run
```

建议默认开启 `--record-run`。

也就是说默认：

- dry-run 不写业务产物。
- 但会写 `.runtime/runs/<run_id>/run-summary.*`。

如果用户不想生成运行记录，可传：

```bash
--no-record-run
```

### CLI 输出要求

输出摘要中增加：

```text
- Run ID: run-xxx
- 运行记录 JSON: .runtime/runs/<run_id>/run-summary.json
- 运行记录 Markdown: .runtime/runs/<run_id>/run-summary.md
```

如果 `--no-record-run`，显示：

```text
- 运行记录: 未生成（--no-record-run）
```

## app.py / langgraph_app.py 要求

保留入口：

```python
run_testcase_generation_workflow(...)
run_langgraph_testcase_generation_workflow(...)
```

建议新增参数：

```python
record_run: bool = True
```

并确保：

- 流程执行完成后再写运行记录。
- 即使 Runtime 执行失败，也要尽量写运行记录，方便排查。
- 如果运行记录写入失败，不应伪装业务流程成功；要在 result warnings 或 errors 中说明。

## .gitignore 要求

更新 `.gitignore`：

```gitignore
.runtime/runs/
```

如果新增 `.runtime/.gitkeep`，确保 `.gitignore` 不会屏蔽 `.runtime/.gitkeep`。

可选写法：

```gitignore
.runtime/runs/
```

不要忽略整个 `.runtime/`，否则后续如果要提交 `.runtime/README.md` 或 `.runtime/.gitkeep` 会麻烦。

## 文档更新要求

### 1. 更新 `runtime/README.md`

补充：

- 011 已加入本地运行记录。
- 默认 dry-run 不写业务产物，但会写运行记录。
- 运行记录默认位于 `.runtime/runs/<run_id>/`。
- 可用 `--no-record-run` 禁用运行记录。
- 运行记录不应提交到 Git。
- 真实 Checkpoint / Resume 后续任务再做。

### 2. 更新根 `README.md`

轻微补充 Runtime 命令说明：

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement --no-record-run
```

说明：默认会生成 `.runtime/runs/` 下的本地运行记录。

### 3. 可选更新 `docs/architecture/production-agent-runtime-roadmap.md`

说明当前进展：

```text
011 已加入本地运行记录；真正可恢复 Checkpoint 和 Resume 后续实现。
```

## 测试要求

新增或更新测试：

```text
tests/unit/test_runtime_run_records.py
```

至少覆盖：

1. `generate_run_id()` 格式正确。
2. dry-run 默认生成运行记录。
3. `record_run=False` 不生成运行记录。
4. 运行记录 JSON 存在且包含 `run_id`、`success`、`orchestration`、`executed_nodes`、`loaded_files`、`wrote_file`。
5. 运行记录 Markdown 存在且包含节点轨迹和审核状态。
6. 失败流程也能生成运行记录，例如不支持的意图。
7. 运行记录中不保存完整 `draft_artifact`，只保存 preview 或不保存。

保留 010 的 `tests/unit/test_runtime_langgraph.py`，必要时适配新增字段。

## 文档一致性校验

如果 README 或架构文档中引用了新增文件路径，例如：

```text
runtime/records/run_recorder.py
```

请确保文件存在，避免 `scripts/validate_docs_consistency.py` 报错。

一般不需要把 `.runtime/runs/` 加入文档一致性核心目录检查，因为它是本地运行产物。

## 验收命令

完成后尽量执行：

```bash
pip install -e .
python -m runtime.cli --help
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement --no-record-run
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/sample-login-requirement
python scripts/run_pytest.py
pytest
ruff check .
```

如果使用本地虚拟环境，请优先：

```bash
.venv\Scripts\activate
pip install -e .
```

注意：

- 不要提交 `.venv/`。
- 不要提交 `.runtime/runs/` 下的运行记录。
- 如果执行命令生成了 `.runtime/runs/`，提交前确认未纳入 Git。

如果某个命令未执行，完成回执中必须说明原因，不能写成通过。

## 不做事项

本任务不要做：

1. 不实现 LangGraph Checkpointer。
2. 不实现 Resume 命令。
3. 不引入数据库。
4. 不接真实 LLM。
5. 不读取 API Key。
6. 不执行真实测试。
7. 不归档需求。
8. 不覆盖已有测试用例文件。
9. 不实现复杂审批 UI。

## 提交要求

直接提交到 `master`。

建议 Commit message：

```text
feat: add runtime run records
```

## 完成后的回复要求

必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复，只输出摘要，不粘贴完整文件或完整 diff。

完成回执必须包含：

1. 变更摘要。
2. 修改文件列表。
3. 是否新增 run_id。
4. 是否新增 `.runtime/runs/<run_id>/run-summary.json` 和 `.md`。
5. dry-run 是否仍不写业务产物。
6. `--no-record-run` 是否可用。
7. `.runtime/runs/` 是否已加入 `.gitignore`。
8. 已执行的验收命令和结果。
9. 未执行命令及原因。
10. 待人工确认点。
11. 下一步建议。

## 下一步预告

011 完成并审核通过后，下一任务建议：

```text
012-add-runtime-human-review-command.md
```

目标：把 Human Review Gate 从“状态门”升级为可记录人工审核动作的 CLI 命令，例如 approve / reject / needs_changes，但仍不接 Web UI。