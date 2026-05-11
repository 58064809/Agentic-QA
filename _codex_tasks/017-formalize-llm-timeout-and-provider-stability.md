# 任务 017：规范化 LLM 超时与 Provider 稳定性配置

## 任务背景

今天为了真实需求评审排障，仓库中已经临时修复了 OpenAI-compatible Adapter：

1. `responses.create` 优先使用用户已验证通过的纯文本 `input` 方式。
2. 给 OpenAI client 增加了超时时间。
3. 禁用了 SDK 自动重试，避免命令看起来长期卡住。

该修复是为了当天评审不中断的热修复。后续需要由 Codex 正式整理为可维护实现。

## 任务目标

将当前 LLM 调用稳定性处理正式化，避免后续 Runtime 在 LLM 卡住、Provider 不兼容或返回慢时影响需求分析和测试用例生成。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不提交任何 API Key、`.env`、`.venv/`、`.runtime/runs/`。
4. 不更换当前 OpenAI-compatible provider 设计。
5. 不接新模型平台。
6. 默认 LLM 仍然关闭，必须 `--use-llm` 才启用。
7. LLM 失败时仍要能降级或给出清晰错误，不输出大段堆栈。

## 需要处理的内容

### 1. 超时配置化

当前 Adapter 内的超时值是代码常量。请将其配置化，建议支持环境变量：

```text
FREEMODEL_TIMEOUT_SECONDS
FREEMODEL_MAX_RETRIES
```

默认建议：

```text
FREEMODEL_TIMEOUT_SECONDS=180
FREEMODEL_MAX_RETRIES=0
```

要求：

- 值非法时使用默认值，并给 warning 或内部错误摘要。
- 不影响现有 `FREEMODEL_API_KEY`、`FREEMODEL_BASE_URL`、`FREEMODEL_MODEL`。

### 2. 保持 freemodel 兼容调用

`responses.create` 优先使用纯文本 input：

```python
client.responses.create(model=model, input="...")
```

不要恢复成 role-list input。

保留 chat completions fallback，但不要让 fallback 导致长时间卡住。

### 3. CLI 输出友好化

如果 LLM 超时或失败，Runtime 摘要应能清晰看到：

- LLM enabled
- LLM used
- calls
- 错误摘要
- 是否降级

### 4. 单元测试

新增或更新测试，至少覆盖：

1. 默认 timeout 为 180 秒。
2. 环境变量可覆盖 timeout。
3. 环境变量非法时使用默认值。
4. OpenAI client 创建时传入 timeout 和 max_retries。
5. `responses.create` 使用纯文本 input。
6. `responses.create` 失败后 fallback 到 chat completions。
7. 两种调用都失败时错误信息包含两个失败摘要。

测试必须 mock，不真实调用外部 API。

### 5. 文档更新

更新：

```text
README.md
runtime/README.md
```

说明：

- LLM 默认关闭。
- `--use-llm` 才启用。
- 可通过 `FREEMODEL_TIMEOUT_SECONDS` 控制等待时间。
- Provider 失败时会记录到 run record。

## 验收命令

完成后执行：

```bash
python scripts/validate_docs_consistency.py
pytest
ruff check .
python -m runtime.cli --help
```

## 完成回执要求

必须说明：

1. 是否已配置化 LLM timeout。
2. 是否保留纯文本 responses input。
3. 是否补充 mock 测试。
4. pytest、ruff、文档校验结果。
