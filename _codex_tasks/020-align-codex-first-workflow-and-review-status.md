# 任务 020：调整为 Codex-first 工作流，并规范人工确认/评审状态

## 任务背景

经过真实需求评审验证，当前阶段不再把 Runtime LLM 作为主线能力。真实可用链路应调整为：

```text
PDF/Word/TXT/HTML -> requirement.md
Codex 读取 requirement.md / api-doc.md / 仓库规则
Codex 生成需求分析和测试用例
人工评审确认
Codex 按评审意见增量修订
必要时导出中文命名评审文件
```

Runtime CLI 继续保留，但定位为辅助工具：文档归一化、结构校验、运行记录、未来自动化能力预留。Runtime LLM 只做预留，不作为当前交付依赖。

## 任务目标

1. 明确当前主线是 Codex-first，不依赖 Runtime LLM。
2. 明确 PyCharm Chat / Codex Chat 可以直接接收自然语言命令，例如“帮我分析 XXX 需求”。
3. 规范人工确认、评审完成、评审意见待处理等状态。
4. 规范重复生成时的覆盖/增量/版本化策略。
5. 规范 PDF 转 Markdown 后的轻量清洗策略。
6. 规范对外评审导出文件的中文命名策略。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不删除 Runtime，不删除 LLM 预留能力。
4. 不调用外部 LLM Provider。
5. 不提交真实业务 PDF、`.env`、`.venv/`、`.runtime/runs/`。
6. 不自研复杂 PDF/图片解析，不做 OCR，不做视觉模型。
7. 完成后按 `rules/codex-output-rules.md` 输出摘要回执。

## 需要更新的文档

至少更新：

```text
README.md
COMMANDS.md
runtime/README.md
rules/review-gate-rules.md
rules/status-rules.md
rules/artifact-path-rules.md
rules/naming-rules.md
```

如果缺少某个文件，请先按路径确认，不要仅依赖搜索。

## 1. Codex-first 工作流说明

README 和 COMMANDS 中需要明确：

- 当前阶段主线不是 `python -m runtime.cli ... --use-llm`。
- 日常工作推荐在 PyCharm Chat / Codex Chat 中直接自然语言命令驱动。
- 示例命令：

```text
帮我分析 prd/<需求名> 需求，按仓库规则输出需求分析。
基于 prd/<需求名> 的需求分析生成测试用例。
根据评审意见增量修订 prd/<需求名> 的需求分析和测试用例。
```

- Codex 应读取 `COMMANDS.md`、`workflows/`、`tasks/`、`rules/`、`skills/`、`knowledge/` 和目标 PRD 工作区。
- Runtime CLI 用于文档转换、校验、运行记录和未来自动化预留。
- Runtime LLM 默认关闭，作为预留能力，不作为当前真实需求交付依赖。

## 2. 人工确认/评审状态规范

请在 `rules/status-rules.md` 和 `rules/review-gate-rules.md` 中补充状态定义。

建议状态：

```text
needs_human_review       AI 已生成，等待人工评审
reviewed                 已完成评审，但可能还有待处理意见
needs_revision           评审后需要修改
approved                 人工确认通过，可作为后续输入
rejected                 人工否决，需要重新生成或重做
archived                 已归档
```

需要定义“什么算确认过/评审过”：

- 你人工打开并阅读了对应产物。
- 你在 Chat 中明确说“这版通过”“已评审”“按评审意见修改完成”“确认可以作为后续输入”。
- 或在产物 front matter / metadata 中更新状态和 reviewer 信息。

建议 front matter：

```yaml
---
status: reviewed
artifact_type: requirement_analysis
human_review_required: false
reviewed_by: user
reviewed_at: 2026-05-11
review_notes: 已完成产品评审，待补充 xxx 规则
---
```

如果只是“生成出来了”，不算确认；如果只是“看了一眼”，不算 approved；如果评审会上有问题未处理，应是 `needs_revision` 或 `reviewed` 加 review_notes。

## 3. 覆盖/增量/版本化策略

补充规则：

- `needs_human_review`：允许覆盖，但建议先说明覆盖原因。
- `needs_revision`：允许增量修订，不建议整份重写。
- `reviewed`：默认只做增量修订，保留评审意见。
- `approved`：禁止直接覆盖，只能追加补充或新建版本。
- 想重新生成对比版时，使用 `*-v2.md` 或复制新 PRD 工作区。

建议：

```text
评审前：可以覆盖草稿
评审后：优先增量修订
确认通过后：禁止覆盖，只能新版本或补充文件
```

## 4. Markdown 清洗策略

当前 MarkItDown/PDF 转换后的 `requirement.md` 可能存在乱码、分页符、异常断行和控制字符。

本任务只做规则和可选轻量脚本，不做复杂自研解析。

建议新增或规划：

```text
scripts/clean_markdown.py
```

要求：

- 只做轻量清洗：去控制字符、规范空行、清理明显分页符、修复连续异常空格。
- 不修改业务语义。
- 默认输出到 `requirement.cleaned.md`，不覆盖 `requirement.md`。
- 需要覆盖时必须显式参数。
- 不处理图片，不 OCR，不分析原型图。

文档要说明成熟工具优先级：

- MarkItDown：默认文档转 Markdown。
- Pandoc：后续可作为 docx 转 Markdown 候选。
- Poppler/pdftotext：后续可作为 PDF 文本提取候选。
- OCR 工具只在扫描件必须识别时再考虑，当前不做。

## 5. 中文导出命名策略

内部产物路径保持英文固定命名，便于脚本和 Codex 路由：

```text
10-analysis/requirement-analysis.md
20-testcases/testcases.md
80-reports/qa-report-draft.md
```

对外评审允许新增中文命名导出文件：

```text
exports/<需求标题>-需求分析.md
exports/<需求标题>-测试用例.md
exports/<需求标题>-QA评审摘要.md
```

要求：

- 内部主文件不改名。
- 导出文件可以中文，便于发给产品/领导/飞书。
- 后续可新增导出脚本，但本任务至少先补规则文档。

## 6. COMMANDS 路由增强

在 `COMMANDS.md` 中补充自然语言触发：

```text
帮我分析 XXX 需求
帮我生成 XXX 的测试用例
根据评审意见修订 XXX 需求分析和用例
将 XXX 需求产物导出为中文评审文件
标记 XXX 需求分析已评审/已确认
```

并说明：

- 没有 PRD 工作区时先定位或创建。
- 已有产物时先检查状态，再决定覆盖或增量。
- 若状态为 approved，不得直接覆盖。

## 7. 测试/校验要求

如果只改文档，至少执行：

```bash
python scripts/validate_docs_consistency.py
pytest
ruff check .
```

如果新增 `scripts/clean_markdown.py`，需要新增测试：

```text
tests/unit/test_clean_markdown.py
```

至少覆盖：

- 去除控制字符。
- 保留中文正文。
- 默认不覆盖原文件。
- 输出 cleaned 文件。

## 完成回执要求

必须说明：

1. 是否已明确 Codex-first 主线。
2. Runtime LLM 是否已调整为预留能力说明。
3. 什么算人工确认/评审过。
4. 覆盖/增量/版本化规则是什么。
5. Markdown 清洗策略是否已补充。
6. 中文导出命名策略是否已补充。
7. 执行了哪些校验命令。
