# 任务 010：接入 LangGraph StateGraph 最小流程

## 任务目标

在 009 已完成 `runtime/` 最小骨架后，本任务正式接入 LangGraph 的 `StateGraph`，把当前手写顺序执行节点升级为 LangGraph 编排流程。

本任务仍然不是完整生产级 Runtime，也不接入真实 LLM。010 只做：

1. 引入 LangGraph 作为可选但实际使用的流程编排依赖。
2. 用 `StateGraph` 编排现有测试用例生成节点。
3. 保留 009 的 dry-run / `--approve-write` 行为。
4. 保留确定性节点、确定性文件读写和 Human Review Gate。
5. 不调用 LangChain ChatModel，不读取 API Key，不访问外部网络。
6. 新增测试覆盖 LangGraph 流程、条件路由和失败中断。

目标是让 Agentic-QA 的第 2 阶段 Runtime 从“骨架顺序执行”升级为“真正由 LangGraph 编排的最小可运行 Graph”。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 允许引入 `langgraph` 依赖，但不要引入真实模型调用依赖。
4. 不接入 OpenAI、Anthropic、LangChain ChatModel，不读取任何 API Key。
5. 不连接真实业务环境，不执行真实测试，不归档。
6. 不实现 Web UI、数据库、向量库或复杂持久化。
7. 必须保留 009 的 CLI 使用方式。
8. 默认 dry-run 仍然不写文件。
9. `--approve-write` 仍然只允许写入 `prd/<id>/20-testcases/testcases.md`，且不得覆盖已存在文件。
10. Runtime 仍必须复用 `workflows/`、`prompts/`、`rules/`、`skills/`、`knowledge/`，不得把 Prompt / Rules / Skills 全部硬编码进 Python。
11. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 背景

009 已实现：

```text
runtime/
├── cli.py
├── graph/app.py
├── graph/state.py
├── graph/nodes/
├── schemas/runtime_result.py
└── tools/
```

当前 `runtime.graph.app.run_testcase_generation_workflow()` 通过 Python list 顺序调用节点。010 要把这段升级为 LangGraph `StateGraph`。

注意：010 的目标是流程编排升级，不是智能生成能力升级。`testcase_generation_node` 仍然可以保持 009 的 Runtime Skeleton 草稿生成方式。

## 依赖要求

更新 `pyproject.toml`：

```toml
"langgraph>=0.2"
```

如果安装或 CI 兼容性需要更具体版本，可以按当前环境调整，但不要引入过多额外依赖。

不要新增：

```text
langchain-openai
langchain-anthropic
openai
anthropic
chromadb
faiss
```

除非后续任务明确授权。

## 推荐实现方式

### 1. 保留原节点函数

保留 009 已有节点：

```text
intent_router_node
workflow_selector_node
context_loader_node
testcase_generation_node
testcase_quality_check_node
human_review_node
artifact_writer_node
metadata_update_node
```

不要把节点逻辑全部搬进 `app.py`。

### 2. 新增 LangGraph 编排文件

建议新增或改造：

```text
runtime/graph/langgraph_app.py
```

实现：

```python
build_testcase_generation_graph(repo_root: Path)
run_langgraph_testcase_generation_workflow(...)
```

`build_testcase_generation_graph()` 负责创建 `StateGraph`。

`run_langgraph_testcase_generation_workflow()` 负责：

1. 初始化 `QAWorkflowState`。
2. 调用 graph。
3. 返回 `RuntimeResult`。

### 3. 状态对象兼容 LangGraph

当前 `QAWorkflowState` 是 dataclass。LangGraph 更常见的是 `TypedDict` 或 dict 状态。

可以采用以下任一方案：

#### 方案 A：保留 dataclass，对 graph 节点做适配

- 对外仍使用 `QAWorkflowState`。
- LangGraph 内部用 dict。
- 新增 `to_graph_state()` / `from_graph_state()` 转换函数。

#### 方案 B：把 `QAWorkflowState` 改成 `TypedDict`

- 需要小心修改现有节点和测试。
- 如果改动过大，不建议本任务做。

优先推荐方案 A，风险更小。

### 4. 条件路由要求

010 必须体现 LangGraph 的价值，不要只是把所有节点线性连起来。

至少实现一个条件路由：

```text
testcase_quality_check_node
  ├── 有 errors 或 quality_errors → END
  └── 无错误 → human_review_node
```

或者：

```text
intent_router_node
  ├── 未识别意图 → END
  └── 已识别 → workflow_selector_node
```

推荐两个都做：

```text
START
  ↓
intent_router_node
  ├── errors → END
  └── ok → workflow_selector_node
        ↓
        context_loader_node
          ├── errors → END
          └── ok → testcase_generation_node
                ↓
                testcase_quality_check_node
                  ├── errors / quality_errors → END
                  └── ok → human_review_node
                        ↓
                        artifact_writer_node
                          ↓
                          metadata_update_node
                            ↓
                            END
```

### 5. app.py 兼容要求

为了不破坏 009 的 CLI 和测试，`runtime/graph/app.py` 中的：

```python
run_testcase_generation_workflow(...)
```

应继续存在。

可以让它内部调用新的 LangGraph 实现：

```python
return run_langgraph_testcase_generation_workflow(...)
```

如果 LangGraph 未安装，必须给出清晰错误，而不是堆栈一坨。

但因为 010 会把 `langgraph` 加入依赖，正常 `pip install -e .` 后应该可用。

### 6. CLI 保持不变

以下命令必须继续可用：

```bash
python -m runtime.cli --help
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement --approve-write
```

CLI 输出中可以补充：

```text
- 编排方式: LangGraph StateGraph
```

但不要输出完整草稿文件。

## 测试要求

新增或更新：

```text
tests/unit/test_runtime_langgraph.py
```

至少覆盖：

1. `build_testcase_generation_graph()` 可以成功构建 graph。
2. dry-run 通过 LangGraph 执行，不写文件。
3. `--approve-write` 通过 LangGraph 执行，在目标文件不存在时写入草稿。
4. 已存在 `testcases.md` 时，不覆盖并返回错误。
5. 不支持的意图会提前结束，不继续执行 context_loader / generation / writer。
6. 缺少 PRD 必需文件时提前结束，不写文件。
7. 质量检查失败时不进入写入节点。

保留 009 的 `tests/unit/test_runtime_skeleton.py`，必要时适配，但不要删除核心覆盖。

## 文档更新要求

### 1. 更新 `runtime/README.md`

补充：

- 010 已接入 LangGraph `StateGraph`。
- 当前仍不接入真实 LLM。
- 当前仍不接入持久化。
- 当前 Graph 只支持测试用例生成 dry-run / approve-write 草稿。
- Human Review Gate 仍然是状态门，不是复杂交互审批。

### 2. 更新根 `README.md`

轻微更新 Runtime Skeleton 说明：

- Runtime 现在使用 LangGraph `StateGraph` 编排最小流程。
- 使用命令不变。
- 当前不是生产完整 Runtime。

### 3. 可选更新 `docs/architecture/production-agent-runtime-roadmap.md`

如果修改，明确 010 完成的是：

```text
StateGraph 编排已接入，但真实 LLM、持久化和复杂 Human-in-the-loop 仍在后续任务。
```

## 文档一致性检查

如果新增了 `runtime/graph/langgraph_app.py`，可以不强制纳入 `scripts/validate_docs_consistency.py` 的核心文件检查。

但如果 README 或文档引用了该路径，且路径确实存在，则检查应通过。

## 验收命令

完成后尽量执行：

```bash
pip install -e .
python -m runtime.cli --help
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/sample-login-requirement
python scripts/run_pytest.py
pytest
ruff check .
```

如果本地已经有 `.venv`，请优先在 `.venv` 中执行：

```bash
.venv\Scripts\activate
pip install -e .
```

注意：

- 不要提交 `.venv/`。
- `.gitignore` 已包含 `.venv/`，但仍需确认没有误提交虚拟环境文件。

如果某个命令未执行，完成回执中必须说明原因，不能写成通过。

## 不做事项

本任务不要做：

1. 不接入真实 LLM。
2. 不引入 OpenAI / Anthropic SDK。
3. 不读取 API Key。
4. 不实现持久化 Checkpointer。
5. 不接 PostgreSQL / SQLite。
6. 不实现复杂审批 UI。
7. 不执行真实测试。
8. 不生成 API/UI 自动化脚本。
9. 不归档需求。
10. 不覆盖已有测试用例文件。

## 提交要求

直接提交到 `master`。

建议 Commit message：

```text
feat: integrate langgraph stategraph runtime
```

## 完成后的回复要求

必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复，只输出摘要，不粘贴完整文件或完整 diff。

完成回执必须包含：

1. 变更摘要。
2. 修改文件列表。
3. 是否已引入 LangGraph 依赖。
4. 是否已接入 `StateGraph`。
5. 条件路由说明。
6. CLI 使用命令。
7. dry-run 是否仍不写文件。
8. `--approve-write` 是否仍不覆盖已有文件。
9. 已执行的验收命令和结果。
10. 未执行命令及原因。
11. 待人工确认点。
12. 下一步建议。

## 下一步预告

010 完成并审核通过后，下一任务建议：

```text
011-add-runtime-checkpoint-and-run-records.md
```

目标：加入轻量运行记录和可恢复基础，但仍不接真实业务环境。