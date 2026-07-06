# QA 报告生成

`qa_report` 用于汇总 PRD 工作区内已生成的 QA 产物、Review Gate 状态、执行缺口、风险和待确认项，生成可人工审核的 QA 报告草稿。

## 输入来源

- `prd/<需求ID>/input/requirement.md`：需求正文。
- `prd/<需求ID>/input/api.md`：接口文档，可选。
- `prd/<需求ID>/artifacts/requirement-analysis.md`：正式需求分析，可选。
- `prd/<需求ID>/artifacts/testcases.md`：正式测试用例，可选。
- `prd/<需求ID>/artifacts/api-test-draft.md`：接口测试草稿，可选。
- `prd/<需求ID>/artifacts/ui-test-draft.md`：UI 自动化草稿，可选。
- `prd/<需求ID>/artifacts/api-discovery-report.md`：接口发现报告，可选。
- `prd/<需求ID>/artifacts/execution-report.md`、`failure-analysis.md`、`bug-draft.md`：执行和缺陷相关产物，可选。
- `prd/<需求ID>/reviews/*.review.yml`：人工确认状态。

## 输出路径

- 候选产物：`prd/<需求ID>/runs/<run_id>/artifact-preview.md`
- 正式产物：`prd/<需求ID>/artifacts/qa-report.md`
- Review 记录：`prd/<需求ID>/reviews/qa-report.review.yml`
- 历史索引：`prd/<需求ID>/artifacts/history/qa-report/index.yml`

## 质量边界

- 默认只生成报告草稿，必须经过 Review Gate 后才能 promote 为正式 `qa-report.md`。
- 未读取到真实执行结果时，不允许编造通过率、失败数、缺陷数或上线结论。
- 不允许把未确认产物当作正式 QA 结论。
- 不粘贴完整测试用例表、完整需求分析或完整执行日志，只输出摘要、风险和缺口。
- token、Cookie、密码、密钥等敏感信息不得进入报告。

## 典型命令

```bash
python -m runtime.cli "基于 prd/sample-login-requirement 生成 QA 报告"
```

确认后发布：

```bash
python -m runtime.cli "QA 报告通过，发布正式产物 prd/sample-login-requirement"
```
