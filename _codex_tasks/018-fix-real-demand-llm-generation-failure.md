# 任务 018：修复真实需求 LLM 生成失败问题

## 任务背景

真实需求已经完成 PDF 到 `requirement.md` 的归一化，但在 `--use-llm` 生成需求分析时，Provider 调用失败，随后降级产物未通过评审级质量门，最终没有写入需求分析和测试用例。

当前目标是：尽快让真实需求稳定产出可评审的 `requirement-analysis.md` 和 `testcases.md`。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不提交任何密钥、`.env`、`.venv/`、`.runtime/runs/`。
4. 不接新平台、不做 Web UI、不做数据库。
5. 默认 LLM 仍然关闭，必须显式参数才启用。
6. LLM 失败时不能静默输出低质量评审产物。
7. 所有外部调用测试必须 mock，不真实请求外部服务。

## 必须修复

### 1. 新增 Provider smoke test

新增脚本：

```text
scripts/llm_smoke_test.py
```

用于快速验证当前本地 Provider 配置是否可用。

要求：

- 复用 Runtime 当前 Adapter。
- 发送很短的中文 prompt。
- 输出 provider、base_url、model、是否成功、错误摘要。
- 不输出密钥。

### 2. 保留纯文本 responses input

当前 Runtime 已改为纯文本 input 调用方式，请保持，不要恢复为 role-list input。

### 3. 处理无效 fallback

当前 chat fallback 对当前 Provider 不稳定。请改成可配置，默认关闭 fallback，避免多等一次无效请求。

建议变量：

```text
FREEMODEL_ENABLE_CHAT_FALLBACK=false
```

### 4. 新增轻量 LLM 模式

为真实需求评审增加轻量模式，减少上下文过大导致 Provider 失败。

建议 CLI 参数：

```bash
--fast-llm
```

如果 CLI 改动风险较大，可以用环境变量实现。

轻量模式要求：

- 只保留 `requirement.md`、可选 `api-doc.md`、必要输出格式和质量标准。
- 不塞 AGENTS、COMMANDS、大量 rules、skills、knowledge。
- 适用于今天真实需求评审产物生成。

目标命令：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/<id> --use-llm --fast-llm --approve-write
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/<id> --use-llm --fast-llm --approve-write
```

### 5. 输入长度配置化

将 LLM Prompt 最大输入长度配置化。

建议支持：

```text
FREEMODEL_MAX_INPUT_CHARS
```

默认可以从 12000 降到 8000。

非法值使用默认值，并记录 warning。

### 6. 质量门失败时保留 debug 草稿

如果生成了草稿但质量门失败，请写入本地 debug 文件：

```text
.runtime/debug/<run_id>/requirement-analysis-draft.md
.runtime/debug/<run_id>/testcases-draft.md
```

要求：

- `.runtime/debug/` 加入 `.gitignore`。
- CLI 摘要展示 debug 路径。
- 不提交 debug 文件。

## 文档更新

更新：

```text
README.md
runtime/README.md
```

说明：

- 真实需求建议先运行 smoke test。
- 真实需求建议先 analyze，再 generate-testcases。
- 如果 Provider 不稳定，使用 fast-llm。
- Skeleton 降级产物不能直接作为评审产物。

## 测试要求

新增或更新测试，至少覆盖：

1. smoke test 不输出密钥。
2. fast-llm 模式 Prompt 更短。
3. fast-llm 模式仍包含需求正文和接口文档。
4. fallback 默认关闭时不调用 chat completions。
5. 最大输入长度可配置。
6. 非法最大输入长度使用默认值。
7. 质量门失败时生成 debug 草稿。

## 验收命令

完成后执行：

```bash
python scripts/llm_smoke_test.py
python scripts/validate_docs_consistency.py
pytest
ruff check .
python -m runtime.cli --help
```

## 完成回执要求

必须说明：

1. 是否新增 smoke test。
2. 是否新增 fast-llm 或等效轻量模式。
3. 是否默认关闭无效 fallback。
4. 是否支持输入长度配置。
5. 是否写 debug 草稿。
6. pytest、ruff、文档校验结果。
