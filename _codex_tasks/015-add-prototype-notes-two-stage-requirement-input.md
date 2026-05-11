# 任务 015：新增 prototype-notes 两段式需求输入流程

## 任务目标

真实需求经常包含 Word/PDF 文本和原型图。当前 013 已接入 MarkItDown，可将 Word/PDF/TXT/HTML 等需求文档归一化为 `requirement.md`；但原型图里的按钮、字段、布局、弹窗和交互状态，不能仅靠 Markdown 文本链路稳定识别。

本任务新增两段式需求输入流程：

```text
第一段：需求文本归一化
Word/PDF/TXT/HTML -> MarkItDown -> requirement.md

第二段：原型图说明归一化
人工补充或后续视觉模型生成 -> prototype-notes.md

最终分析输入：
requirement.md + prototype-notes.md + api-doc.md -> 需求分析 -> 测试用例
```

目标不是取消 `requirement.md`，而是明确：

- `requirement.md` 负责稳定承载需求文本；
- `prototype-notes.md` 负责稳定承载原型图交互说明；
- Runtime 分析时同时读取两者。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不提交真实业务 Word/PDF、原型图、`.venv/`、`.env`、`.runtime/runs/`。
4. 不提交任何密钥。
5. 不接 Web UI、数据库、向量库或复杂 RAG。
6. 不调用视觉模型，不上传图片二进制。
7. 本任务只做 `prototype-notes.md` 模板、读取、质量提醒和文档说明。
8. 保持当前 MarkItDown 文本归一化流程，不要删除 `requirement.md` 链路。
9. 完成后必须按 `rules/codex-output-rules.md` 输出可审核回执。

## 设计结论

不要直接把 Word/PDF 作为唯一输入跳过 Markdown。

原因：

1. Markdown 可审计、可 diff、可人工修改。
2. MarkItDown 能稳定提取正文，但不能保证理解图片内容。
3. 当前 Runtime LLM Adapter 是文本链路，不会把图片二进制传给多模态模型。
4. 原型图内容必须通过 `prototype-notes.md` 明确描述后再进入分析。

推荐最终 PRD 工作区结构：

```text
prd/<需求名>/
├── requirement.docx        # 可选，原始需求文档，不建议提交真实敏感文件
├── requirement.pdf         # 可选，原始需求文档，不建议提交真实敏感文件
├── requirement.md          # MarkItDown 或人工整理后的需求正文
├── prototype-notes.md      # 原型图文字说明，重点补按钮、字段、状态、交互
├── api-doc.md              # 可选，接口文档
├── metadata.yml
├── 10-analysis/
│   └── requirement-analysis.md
└── 20-testcases/
    └── testcases.md
```

## 新增模板要求

新增模板：

```text
knowledge/templates/prototype-notes-template.md
```

模板至少包含：

```markdown
# 原型图说明

> 状态：needs_human_review
> 用途：补充 Word/PDF/图片原型中无法稳定转成 Markdown 的页面结构、字段、按钮、交互和状态。

## 1. 原型图清单

| 编号 | 页面/弹窗 | 图片来源 | 说明状态 |
|---|---|---|---|
| P01 | 待补充 | 待补充 | needs_human_review |

## 2. 页面结构说明

### P01：页面名称

- 页面入口：
- 页面目标：
- 展示字段：
- 操作按钮：
- 默认状态：
- 空状态：
- 异常状态：
- 权限差异：
- 跳转逻辑：

## 3. 表单与字段规则

| 页面 | 字段 | 类型 | 必填 | 格式/范围 | 默认值 | 错误提示 | 备注 |
|---|---|---|---|---|---|---|---|

## 4. 按钮与交互规则

| 页面 | 按钮/操作 | 可点击条件 | 点击后行为 | 成功反馈 | 失败反馈 | 防重复/幂等 |
|---|---|---|---|---|---|---|

## 5. 状态与展示规则

| 页面 | 业务状态 | 展示内容 | 可操作项 | 禁用项 | 提示文案 |
|---|---|---|---|---|---|

## 6. 弹窗、提示与错误文案

| 触发场景 | 弹窗/提示 | 用户操作 | 系统结果 |
|---|---|---|---|

## 7. 埋点、日志、消息与通知

| 场景 | 埋点/日志/消息 | 触发条件 | 字段/内容 | 是否待确认 |
|---|---|---|---|---|

## 8. 待确认问题

- [ ] 原型图中未明确的页面入口是什么？
- [ ] 字段必填、格式、边界和错误提示是否已确认？
- [ ] 不同角色/状态下按钮是否可见、可点、禁用？
```

## Runtime 读取要求

更新上下文加载逻辑，使 analyze / mvp / generate-testcases 在存在以下文件时自动读取：

```text
prd/<需求名>/prototype-notes.md
```

要求：

1. 文件存在则加载并进入 LLM Prompt / Skeleton 分析上下文。
2. 文件不存在不报错，但给 warning：`未发现 prototype-notes.md，如需求包含原型图，建议补充原型图说明。`
3. 如果 `requirement.md` 中出现图片引用语法，例如 `![](...)` 或 `![xxx](...)`，但没有 `prototype-notes.md`，必须给 warning。
4. 运行记录中记录是否加载了 `prototype-notes.md`。

## Prompt 更新要求

更新 `runtime/llm/prompt_builder.py`：

需求分析 Prompt 增加读取：

```text
prd/<需求名>/prototype-notes.md
knowledge/templates/prototype-notes-template.md
```

测试用例 Prompt 增加读取：

```text
prd/<需求名>/prototype-notes.md
knowledge/templates/prototype-notes-template.md
```

Prompt 需要明确：

- 如果存在 `prototype-notes.md`，必须基于其中的页面、字段、按钮、状态、弹窗和权限说明生成分析和用例。
- 如果缺少 `prototype-notes.md` 且需求含图片，只能基于文字生成，并在待确认问题中提示原型图信息不足。

## 需求分析输出增强

更新需求分析生成逻辑，使 `requirement-analysis.md` 能体现原型信息：

1. `角色与权限` 章节应参考 prototype-notes 中的权限差异。
2. `主流程拆解` 章节应参考页面入口、按钮、跳转逻辑。
3. `分支流程与异常流程` 应参考空状态、异常状态、错误文案。
4. `数据字段与状态流转` 应参考字段规则和状态展示规则。
5. `风险点与影响面` 应提示：缺少原型说明会影响 UI 展示、交互、字段校验和用例覆盖。
6. `待确认问题` 中必须包含原型图相关问题，除非 prototype-notes 已完整提供。

## 测试用例输出增强

更新测试用例生成逻辑，使存在 `prototype-notes.md` 时，至少覆盖：

1. 页面入口和默认展示。
2. 字段展示、必填、格式、边界。
3. 按钮可见、可点击、禁用条件。
4. 点击后跳转、弹窗、提示文案。
5. 不同角色/状态下页面展示差异。
6. 空状态、异常状态、加载失败。
7. 重复点击、防重和幂等。
8. 埋点、日志、消息或通知，如原型说明涉及。

## 文档更新要求

更新：

```text
README.md
runtime/README.md
docs/architecture/production-agent-runtime-roadmap.md
```

说明两段式流程：

```text
requirement.md：需求正文
prototype-notes.md：原型图交互说明
api-doc.md：接口说明
```

并明确：当前不直接分析图片二进制；如需图像识别，后续再做视觉模型接入。

## 可选文档

新增：

```text
docs/architecture/prototype-image-analysis-plan.md
```

说明：

1. 当前阶段使用人工补充 `prototype-notes.md`。
2. 后续阶段可从 Word/PDF 中提取图片到 `assets/prototypes/`。
3. 后续可接入视觉模型生成 `prototype-analysis.md`。
4. 最终分析时同时读取 `requirement.md`、`prototype-notes.md`、`prototype-analysis.md` 和 `api-doc.md`。

## 测试要求

新增或更新测试，至少覆盖：

1. 没有 `prototype-notes.md` 时 analyze/mvp 不失败，但有 warning。
2. `requirement.md` 含 Markdown 图片语法且无 `prototype-notes.md` 时产生 warning。
3. 存在 `prototype-notes.md` 时 context loader 会加载它。
4. LLM Prompt 包含 `prototype-notes.md` 内容。
5. 测试用例生成时能基于 prototype-notes 生成页面/字段/按钮/状态相关用例。

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

1. 是否已新增 prototype-notes 模板。
2. analyze/mvp/generate-testcases 是否会读取 prototype-notes。
3. 缺少 prototype-notes 但需求含图片时是否会 warning。
4. 当前是否仍保留 requirement.md 归一化流程。
5. 当前是否不会直接分析图片二进制。
6. 周一真实需求推荐如何放文件。
