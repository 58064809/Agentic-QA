# Runtime 最小骨架

当前 Runtime 处于最小骨架阶段，用于第 2 阶段 LangGraph Runtime 的后续演进。010 已接入 LangGraph `StateGraph` 编排最小流程，但仍不是生产完整 Runtime。

## 当前能力

- 009 不接入真实 LLM。
- 010 使用 LangGraph `StateGraph` 编排测试用例生成最小流程。
- 011 已加入本地运行记录。
- 当前不接入真实 LLM。
- 当前不接入 LangChain ChatModel。
- 当前不接入持久化 Checkpointer。
- 默认 dry-run，不写入业务产物，但会写运行记录。
- 仅支持测试用例生成流程骨架。
- Runtime 必须读取现有声明式资产，不允许硬编码 Prompt / Rules / Skills。
- Runtime 的写入、执行、归档动作必须经过 Human Review Gate。
- Human Review Gate 当前是状态门，不是复杂交互审批。
- 运行记录默认位于 `.runtime/runs/<run_id>/`，不应提交到 Git。

## 使用命令

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
```

禁用运行记录：

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement --no-record-run
```

显式写入测试用例草稿：

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement --approve-write
```

写入后仍然必须人工审核，状态保持 `needs_human_review`。如果目标 `20-testcases/testcases.md` 已存在，当前骨架默认拒绝覆盖。

## 后续方向

012 再把 Human Review Gate 升级为可记录人工审核动作的 CLI 命令。真实 Checkpoint / Resume 后续任务再做。
