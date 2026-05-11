# 任务 016：调整原型图处理为忽略图片内容但明确 warning

## 任务目标

015 已加入 `prototype-notes.md` 两段式输入能力。但当前用户已决定：暂时不让 Runtime 分析原型图内容，`prototype-notes.md` 只作为可选补充，不强制。

本任务将 015 的策略调整为更简单、更稳的 MVP 策略：

```text
requirement.md：必须分析
api-doc.md：有则分析
prototype-notes.md：有则分析，没有也不阻塞
图片/原型图内容：当前忽略，但必须 warning
```

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不提交真实需求文档、图片、密钥、`.venv/`、`.env`、`.runtime/runs/`。
4. 不做图片识别。
5. 不接新模型或新平台。
6. 不删除 MarkItDown 的 `requirement.md` 归一化流程。
7. 不强制要求每个需求必须提供 `prototype-notes.md`。

## 需要调整的行为

### 1. prototype-notes 改为可选补充

当前没有 `prototype-notes.md` 时可以 warning，但不要让用户感觉这是必填。

建议 warning 文案调整为：

```text
未发现 prototype-notes.md；如需求图片中包含未写入正文的字段、按钮、状态或交互，请人工补充说明，否则 Runtime 将忽略图片内容。
```

### 2. 检测到图片引用时必须强 warning

如果 `requirement.md` 中检测到 Markdown 图片引用，例如：

```markdown
![xxx](xxx.png)
```

必须 warning：

```text
检测到 requirement.md 包含图片/原型图引用；当前 Runtime 不分析图片内容，只基于文本生成需求分析和测试用例。请确认图片中的字段、按钮、状态、弹窗或交互是否已写入正文或 prototype-notes.md。
```

### 3. 需求分析待确认问题必须体现图片被忽略

如果检测到图片引用且没有 `prototype-notes.md`，需求分析的 `待确认问题` 中必须包含：

```text
需求文档包含图片/原型图引用，但当前 Runtime 未分析图片内容；请确认图片中是否存在字段、按钮、状态、弹窗、权限差异或交互规则未写入正文。
```

### 4. 测试用例不得基于图片内容编造

如果缺少 `prototype-notes.md`，测试用例生成不能凭空写图片里的字段、按钮、交互。

可以在草稿中保留待确认方向，但不要写成确定结论。

## Prompt 调整

更新 `runtime/llm/prompt_builder.py`：

1. 继续在存在时读取 `prototype-notes.md`。
2. 明确说明：没有 `prototype-notes.md` 时，不要根据图片猜字段、按钮和交互。
3. 如果上下文提示有图片，必须把图片内容未分析写入待确认问题。

## Runtime 和记录要求

保留 `state.prototype_notes` 和运行记录中的 `prototype_notes` 字段。

确保记录里能看到：

- 是否加载 prototype-notes。
- requirement.md 是否有图片引用。
- warning 文案。

## 文档更新

更新：

```text
README.md
runtime/README.md
docs/architecture/prototype-image-analysis-plan.md
```

说明当前最终策略：

```text
图片内容当前忽略；prototype-notes.md 是可选补充；检测到图片会 warning。
```

## 测试要求

新增或更新测试，至少覆盖：

1. 没有 `prototype-notes.md` 时 analyze/mvp 不失败。
2. 没有 `prototype-notes.md` 时会产生温和 warning。
3. `requirement.md` 含图片引用且无 `prototype-notes.md` 时产生强 warning。
4. 存在 `prototype-notes.md` 时 context loader 会加载它。
5. LLM Prompt 在存在 `prototype-notes.md` 时包含其内容。
6. LLM Prompt 在缺少 `prototype-notes.md` 时要求不要基于图片猜测字段、按钮和交互。
7. 运行记录包含 `prototype_notes` 字段。

## 验收命令

完成后执行：

```bash
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/sample-login-requirement
pytest
ruff check .
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement --no-record-run
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --no-record-run
```

## 完成回执要求

必须说明：

1. prototype-notes 是否已改为可选补充。
2. 检测到图片时是否会 warning。
3. 是否明确不基于图片内容编造字段、按钮和交互。
4. 是否补充相关测试。
5. pytest、ruff、文档校验结果。
