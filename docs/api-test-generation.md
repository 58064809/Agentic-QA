# 接口测试草稿生成

`api_test_draft` 是接口测试能力建设的第一阶段产物。Runtime 只生成接口测试计划、断言策略和 pytest + requests 脚本草稿，不执行真实 HTTP 请求。

## 工作流

```text
需求 / 接口文档 / 已确认测试用例
  ↓
生成接口测试草稿
  ↓
质量检查
  ↓
写入 runs/<run_id>/artifact-preview.md
  ↓
Review Gate
  ↓
promote 到 artifacts/api-test-draft.md
```

## 输入

- `prd/<需求ID>/input/requirement.md`
- `prd/<需求ID>/input/api.md`：可选，有可用内容时优先作为接口事实来源。
- `prd/<需求ID>/artifacts/requirement-analysis.md`：可选，提供业务规则和风险。
- `prd/<需求ID>/artifacts/testcases.md`：可选，提供已确认测试覆盖点。
- `prompts/api-test-generation.md`
- `skills/api-testing.md`

## 无接口文档规则

没有可用 `input/api.md` 时，Runtime 允许生成接口候选点，但必须标记：

```text
待补充接口文档
待确认 URL
待确认 Method
待确认请求字段
待确认响应字段
待确认鉴权方式
```

推断内容不得写成确定接口事实。

## 质量门

`api_test_quality_check_node` 至少检查：

- 输出包含接口清单。
- 输出包含接口测试点矩阵。
- 输出包含 pytest + requests 脚本草稿。
- 输出包含断言策略。
- 无可用接口文档时包含“待补充接口文档”提示。
- 不出现“已执行 / 执行通过 / 实测通过”等执行结论。
- 不包含真实 token、Cookie 或密钥。

## 发布

候选内容先写入：

```text
prd/<需求ID>/runs/<run_id>/artifact-preview.md
```

Review Gate 审核通过后，才允许确定性 promote 到：

```text
prd/<需求ID>/artifacts/api-test-draft.md
```
