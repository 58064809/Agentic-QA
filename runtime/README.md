# Runtime MVP

当前 Runtime 处于 MVP 阶段，用于第 2 阶段 LangGraph Runtime 的后续演进。010 已接入 LangGraph `StateGraph`，011 已加入本地运行记录，012 已打通需求分析与测试用例生成链路，但仍不是生产完整 Runtime。

## 当前能力

- 010 使用 LangGraph `StateGraph` 编排测试用例生成最小流程。
- 011 已加入本地运行记录。
- 012 支持需求分析草稿、测试用例草稿和 MVP 连续链路。
- LLM 默认关闭，必须通过 `--use-llm` 显式启用。
- LLM 配置只从本地环境变量读取：`FREEMODEL_API_KEY`、`FREEMODEL_BASE_URL`、`FREEMODEL_MODEL`。
- 缺少密钥或未启用 LLM 时，Runtime 降级生成 Skeleton 草稿。
- 当前不接入 LangChain ChatModel。
- 当前不接入持久化 Checkpointer。
- 默认 dry-run，不写入业务产物，但会写运行记录。
- `--approve-write` 才允许写入需求分析和测试用例草稿。
- 如果目标文件已存在，默认拒绝覆盖；MVP 连续链路拒绝部分写入。
- Runtime 必须读取现有声明式资产，不允许硬编码 Prompt / Rules / Skills。
- Runtime 的写入、执行、归档动作必须经过 Human Review Gate。
- Human Review Gate 当前是状态门，不是复杂交互审批。
- 运行记录默认位于 `.runtime/runs/<run_id>/`，不应提交到 Git。

## 使用命令

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/sample-login-requirement
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
```

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

写入后仍然必须人工审核，状态保持 `needs_human_review`。如果目标 `10-analysis/requirement-analysis.md` 或 `20-testcases/testcases.md` 已存在，Runtime 默认拒绝覆盖。

显式启用 LLM：

```bash
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --use-llm
```

默认服务地址为 `https://api.freemodel.dev`，默认模型为 `gpt-5.5`。请只在本地环境变量中设置密钥，不要提交 `.env` 或任何密钥文件。运行记录会记录是否启用 LLM、模型、服务地址、调用次数和错误摘要，但不会记录密钥。

## 后续方向

013 再把 Human Review Gate 升级为可记录人工审核动作的 CLI 命令。真实 Checkpoint / Resume 后续任务再做。
