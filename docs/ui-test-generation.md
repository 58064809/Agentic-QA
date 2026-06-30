# UI 自动化草稿生成

`ui_test_draft` 用于从 PRD、需求分析、测试用例和接口文档生成 Playwright UI 自动化草稿。本阶段不启动浏览器，不访问真实环境。

## 工作流

```text
PRD / 需求分析 / 测试用例
  ↓
生成 UI 自动化草稿
  ↓
质量检查
  ↓
写入 runs/<run_id>/artifact-preview.md
  ↓
Review Gate
  ↓
promote 到 artifacts/ui-test-draft.md
```

## 输入

- `input/requirement.md`
- `input/api.md`
- `input/ui-flow.md`（可选）
- `artifacts/requirement-analysis.md`
- `artifacts/testcases.md`
- `prompts/ui-test-generation.md`
- `skills/ui-testing.md`

## 质量门

- 包含页面/入口清单。
- 包含 UI 自动化场景矩阵。
- 包含 Playwright 脚本草稿。
- 包含选择器策略。
- 包含等待与断言策略。
- 包含不适合自动化或需人工确认的场景。
- 不出现“已执行 / 执行通过 / 实测通过”等执行结论。
- 不包含真实账号、token、Cookie 或密钥。
- 不建议在生产环境执行。
