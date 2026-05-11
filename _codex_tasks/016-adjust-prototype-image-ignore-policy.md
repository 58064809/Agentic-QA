# 任务 016：明确不分析原型图，废弃 prototype-notes 输入链路

## 任务目标

用户已明确最终口径：当前 Runtime 不分析原型图，不接视觉模型，也不通过 `prototype-notes.md` 让模型间接分析图片内容。

本任务将 015 的两段式原型输入能力收敛为更硬的策略：

```text
requirement.md：必须分析
api-doc.md：有则分析
图片/原型图：明确忽略
prototype-notes.md：不作为 Runtime 输入，不进入 Prompt，不参与需求分析和测试用例生成
```

如果需求中包含图片或原型图，Runtime 只做两件事：

1. warning：提示图片内容未分析。
2. 待确认问题：提示人工确认图片中是否存在未写入正文的业务信息。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不提交真实需求文档、图片、密钥、`.venv/`、`.env`、`.runtime/runs/`。
4. 不做图片识别。
5. 不上传图片。
6. 不接视觉模型。
7. 不接新平台。
8. 不让 `prototype-notes.md` 进入 LLM Prompt。
9. 不让 `prototype-notes.md` 参与需求分析和测试用例生成。
10. 不删除 MarkItDown 的 `requirement.md` 归一化流程。

## 需要调整的行为

### 1. 移除 prototype-notes 输入链路

请移除或停用 015 中加入的 `prototype-notes.md` 输入能力：

- `mvp_context_loader.py` 不再加载 `prd/<id>/prototype-notes.md`。
- `prompt_builder.py` 不再选择 `prd/<id>/prototype-notes.md`。
- `prompt_builder.py` 不再选择 `knowledge/templates/prototype-notes-template.md`。
- `mvp_generation.py` 不再基于 `prototype-notes.md` 生成分析或用例。
- `README.md`、`runtime/README.md`、架构文档中不再推荐用户补 `prototype-notes.md` 作为输入。

可以保留内部字段名 `prototype_notes` 用于兼容运行记录，但语义必须调整为“图片检测状态”，而不是“原型说明输入”。如果重命名改动过大，可以暂时保留字段名，但文档里要说明已废弃 prototype-notes 输入。

### 2. 检测到图片引用时强 warning

如果 `requirement.md` 中出现 Markdown 图片引用，例如：

```markdown
![xxx](xxx.png)
```

或出现常见图片资源痕迹，例如：

```text
.png
.jpg
.jpeg
media/
images/
```

必须追加 warning：

```text
检测到需求文档包含图片/原型图引用；当前 Runtime 不分析图片内容，只基于 requirement.md 和 api-doc.md 的文本生成需求分析和测试用例。请人工确认图片中是否存在未写入正文的字段、按钮、状态、弹窗、权限差异或交互规则。
```

### 3. 没有图片时不需要提示 prototype-notes

如果没有检测到图片，不要提示用户补充 `prototype-notes.md`。

### 4. 需求分析待确认问题必须体现图片被忽略

如果检测到图片引用，需求分析的 `待确认问题` 中必须包含类似内容：

```text
需求文档包含图片/原型图引用，但当前 Runtime 未分析图片内容；请确认图片中是否存在字段、按钮、状态、弹窗、权限差异或交互规则未写入正文。
```

### 5. 测试用例不得基于图片内容编造

如果检测到图片引用，测试用例生成仍可基于正文继续，但不能凭空写图片里的字段、按钮、页面布局或交互。

可以增加一条待确认类用例或风险说明，提醒图片内容未覆盖，但不要把图片内容当成已知事实。

## Prompt 调整

更新 `runtime/llm/prompt_builder.py`：

1. 只读取 `requirement.md`、`api-doc.md`、已有需求分析、rules、skills、templates、prompts。
2. 不读取 `prototype-notes.md`。
3. 不读取 `knowledge/templates/prototype-notes-template.md`。
4. 明确说明：如果上下文提示有图片，禁止猜测图片中的字段、按钮、页面布局和交互。
5. 必须在待确认问题中提示图片内容未分析。

## Runtime 和记录要求

运行记录中保留图片检测结果即可，例如：

```json
"image_detection": {
  "requirement_has_images": true,
  "warning": "..."
}
```

如果为了减少改动继续使用 `prototype_notes` 字段，也必须改成：

```json
"prototype_notes": {
  "loaded": false,
  "path": null,
  "requirement_has_images": true,
  "warning": "图片内容未分析..."
}
```

但不得记录已加载 `prototype-notes.md`。

## 文档更新

更新：

```text
README.md
runtime/README.md
docs/architecture/prototype-image-analysis-plan.md
```

说明当前最终策略：

```text
图片/原型图当前明确忽略；Runtime 只分析 requirement.md 和 api-doc.md 文本；检测到图片会 warning；不使用 prototype-notes.md。
```

`knowledge/templates/prototype-notes-template.md` 如果已经存在，请删除，或改为废弃说明文件。优先删除，避免后续 Codex 误用。

## 测试要求

新增或更新测试，至少覆盖：

1. 没有图片时 analyze/mvp 不提示 prototype-notes。
2. `requirement.md` 含图片引用时产生强 warning。
3. 即使存在 `prototype-notes.md`，context loader 也不加载它。
4. LLM Prompt 不包含 `prototype-notes.md` 内容。
5. LLM Prompt 明确禁止根据图片猜测字段、按钮、布局和交互。
6. 运行记录包含图片检测 warning 或 `requirement_has_images=true`。
7. 测试用例不会因为存在图片引用而编造图片里的字段、按钮或交互。

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

1. 是否已废弃 prototype-notes 输入链路。
2. 是否已明确不分析图片内容。
3. 检测到图片时是否会 warning。
4. 是否保证 Prompt 不读取 prototype-notes。
5. 是否保证不基于图片内容编造字段、按钮、布局和交互。
6. 是否补充相关测试。
7. pytest、ruff、文档校验结果。
