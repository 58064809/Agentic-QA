# 产物路径规则

本文件定义 Agentic-QA 当前唯一有效的 PRD 工作区路径契约。Runtime、Workflow、Prompt、Agent、Skill、脚本和文档必须使用同一套路径；不保留旧目录兼容、别名映射或双写逻辑。

## 权威来源

路径定义以 `runtime/workspace.py` 的 `ARTIFACT_SPECS`、`ARTIFACT_PREVIEW_FILES`、`WORKSPACE_DIRS` 和 `REQUIRED_WORKSPACE_FILES` 为程序事实源。本文件只解释约束，不得定义与代码不同的第二套结构。

## 输入与元数据

| 数据 | 当前路径 |
|---|---|
| 原始需求 | `prd/<id>/input/requirement.md` |
| 接口文档 | `prd/<id>/input/api.md` |
| 附件 | `prd/<id>/input/attachments/` |
| 需求级元数据 | `prd/<id>/metadata.yml` |

## 候选产物与运行指针

| 数据 | 当前路径 |
|---|---|
| 候选索引 | `prd/<id>/runs/<run-id>/artifact-preview.md` |
| 需求分析候选正文 | `prd/<id>/runs/<run-id>/requirement-analysis.preview.md` |
| 测试用例候选正文 | `prd/<id>/runs/<run-id>/testcases.preview.md` |
| API 测试草稿候选正文 | `prd/<id>/runs/<run-id>/api-test-draft.preview.md` |
| UI 测试草稿候选正文 | `prd/<id>/runs/<run-id>/ui-test-draft.preview.md` |
| 接口发现报告候选正文 | `prd/<id>/runs/<run-id>/api-discovery-report.preview.md` |
| QA 报告候选正文 | `prd/<id>/runs/<run-id>/qa-report.preview.md` |
| 最新运行指针 | `prd/<id>/runs/latest.yml` |
| 运行索引 | `prd/<id>/runs/index.jsonl` |

`artifact-preview.md` 只保存候选文件索引，不承载多产物正文。正式发布必须从 `runs/latest.yml.output_paths` 或指定 run 的具体 `<artifact>.preview.md` 读取候选正文。

## 正式产物、审核与历史版本

| 产物 | 正式路径 | 审核记录 | 历史索引 |
|---|---|---|---|
| 需求分析 | `artifacts/requirement-analysis.md` | `reviews/requirement-analysis.review.yml` | `artifacts/history/requirement-analysis/index.yml` |
| 测试用例 | `artifacts/testcases.md` | `reviews/testcases.review.yml` | `artifacts/history/testcases/index.yml` |
| API 测试草稿 | `artifacts/api-test-draft.md` | `reviews/api-test-draft.review.yml` | `artifacts/history/api-test-draft/index.yml` |
| UI 测试草稿 | `artifacts/ui-test-draft.md` | `reviews/ui-test-draft.review.yml` | `artifacts/history/ui-test-draft/index.yml` |
| 接口发现报告 | `artifacts/api-discovery-report.md` | `reviews/api-discovery-report.review.yml` | `artifacts/history/api-discovery-report/index.yml` |
| QA 报告 | `artifacts/qa-report.md` | `reviews/qa-report.review.yml` | `artifacts/history/qa-report/index.yml` |

以上路径均相对 `prd/<id>/`。

## Runtime 内部记录

Runtime 的图状态、恢复数据和运行摘要写入 `.runtime/runs/<run-id>/`。该目录不是 PRD 正式产物目录，不能被 Prompt 当作业务输入路径。

## 写入规则

1. 生成节点只写 `runs/<run-id>/<artifact>.preview.md` 及伴随结构化文件。
2. Review Gate 只更新 `reviews/*.review.yml` 和运行状态，不直接覆盖正式产物。
3. 只有 `approved` 候选允许由确定性 promote 逻辑写入 `artifacts/`。
4. promote 成功后正式状态才可变为 `confirmed`，旧正式版本进入 `artifacts/history/<artifact>/`。
5. 正式产物、审核记录、历史索引和 `metadata.yml` 必须保持同一 artifact key、run_id 和版本信息。
6. 所有写入默认禁止覆盖已有候选文件；重复执行必须生成新的 run 或明确的新候选文件名。

## 禁止项

以下路径和命名已废弃，仓库规范文件和运行时代码中不得继续引用：

- `prd/<id>/workspace.yml`
- `prd/<id>/analysis/`
- `prd/<id>/cases/`
- `prd/<id>/execution/`
- `prd/<id>/defects/`
- `prd/<id>/report/`
- `test-cases.md`
- `qa-review.md`
- 把 `artifact-preview.md` 当作多产物候选正文

发现旧路径时直接修复或删除引用，不增加兼容读取、兼容写入、fallback 或迁移分支。
