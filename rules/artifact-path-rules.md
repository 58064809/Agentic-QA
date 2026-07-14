# 产物路径规则

所有 QA 产物必须写入对应 PRD 工作区，路径以 `prd/<requirement_id>/` 为根。

## 固定路径

| 产物 | 路径 |
|---|---|
| 原始需求 | `prd/<id>/input/requirement.md` |
| 接口文档 | `prd/<id>/input/api.md` |
| 元数据 | `prd/<id>/metadata.yml` |
| 需求分析 | `prd/<id>/runs/<run_id>/analysis/requirement-analysis.md` |
| 测试用例 | `prd/<id>/runs/<run_id>/cases/test-cases.md` |
| API 测试计划 | `prd/<id>/automation/api/test-plan.md` |
| API 测试脚本 | `prd/<id>/automation/api/generated/` |
| UI 测试脚本 | `prd/<id>/automation/ui/generated/` |
| QA 产物最新指针 | `prd/<id>/runs/latest.yml` |
| QA 产物历史索引 | `prd/<id>/runs/index.jsonl` |
| 执行结果 | `prd/<id>/execution/runs/` |
| 执行报告 | `prd/<id>/execution/runs/latest/summary.md` |
| 失败分析 | `prd/<id>/defects/failure-analysis.md` |
| 缺陷草稿 | `prd/<id>/defects/bug-drafts/` |
| AI 生成 QA 报告草稿 | `prd/<id>/report/qa-review.md` |
| 人工确认正式 QA 报告 | `prd/<id>/report/qa-report.md` |
| 对外评审导出 | `prd/<id>/exports/` |
| 归档索引 | `prd/<id>/archive/index.md` |

## 规则

- 不允许把同一需求的产物散落在仓库根目录。
- Runtime 每轮分析/用例产物必须写入 `prd/<id>/runs/<run_id>/`，不得继续堆放在 `analysis/` 或 `cases/` 根目录。
- `prd/<id>/runs/latest.yml` 指向最新一轮，`prd/<id>/runs/index.jsonl` 追加记录历史轮次。
- 不允许覆盖人工已确认产物；需要修改时生成修订记录、补充文件或新版本。
- 自动化脚本必须放入 `generated/`，人工维护脚本可另建 `manual/`。
- AI 只能生成 `qa-review.md`；`qa-report.md` 是人工确认后的正式报告，可后续生成。
- 内部主产物路径保持英文固定命名，便于脚本、路由和校验。
- 对外评审文件可以使用中文命名，但只能放入 `prd/<id>/exports/`，不得替代内部主文件。

## 覆盖、增量和版本

- `needs_human_review`：允许覆盖草稿，但应说明覆盖原因。
- `needs_revision`：允许按评审意见增量修订，不建议整份重写。
- `reviewed`：默认只做增量修订，必须保留评审意见。
- `approved`：禁止直接覆盖，只能追加补充或新建版本。
- 重新生成对比版时，使用 `*-v2.md`，或复制新的 PRD 工作区。

## Markdown 清洗产物

- 文档转换后的主输入仍是 `prd/<id>/input/requirement.md`。
- 轻量清洗输出使用 `prd/<id>/input/requirement.cleaned.md`。
- 清洗默认不得覆盖 `input/requirement.md`；覆盖必须由用户显式确认。
- 清洗只能处理控制字符、分页符、异常空行和连续异常空格，不得修改业务语义。
- 不处理图片，不做 OCR，不分析原型图。

## 中文导出示例

```text
prd/<id>/exports/<需求标题>-需求分析.md
prd/<id>/exports/<需求标题>-测试用例.md
prd/<id>/exports/<需求标题>-QA评审摘要.md
```
