# Runtime 最小骨架

当前 Runtime 处于最小骨架阶段，用于第 2 阶段 LangGraph Runtime 的后续演进。

## 当前能力

- 009 不接入真实 LLM。
- 009 不强制引入 LangGraph / LangChain 依赖。
- 默认 dry-run，不写入文件。
- 仅支持测试用例生成流程骨架。
- Runtime 必须读取现有声明式资产，不允许硬编码 Prompt / Rules / Skills。
- Runtime 的写入、执行、归档动作必须经过 Human Review Gate。

## 使用命令

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement
```

显式写入测试用例草稿：

```bash
python -m runtime.cli run "帮我生成 sample-login-requirement 的测试用例" --prd prd/sample-login-requirement --approve-write
```

写入后仍然必须人工审核，状态保持 `needs_human_review`。如果目标 `20-testcases/testcases.md` 已存在，当前骨架默认拒绝覆盖。

## 后续方向

010 再接入真实 LangGraph `StateGraph`，但仍不接入真实 LLM。
