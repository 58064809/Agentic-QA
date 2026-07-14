# 命名规则

本仓库只使用当前 Runtime 契约中的名称，不保留旧文件名别名。

## 工作区与运行记录

- 需求目录使用小写字母、数字和连字符，例如 `sample-login-requirement`。
- 运行 ID 使用 `run-<时间>-<随机后缀>` 格式，由 Runtime 生成。
- 需求级元数据固定为 `metadata.yml`。
- 最新运行指针固定为 `runs/latest.yml`，运行索引固定为 `runs/index.jsonl`。

## 候选产物

候选正文固定使用 `<artifact>.preview.md`：

- `requirement-analysis.preview.md`
- `testcases.preview.md`
- `api-test-draft.preview.md`
- `ui-test-draft.preview.md`
- `api-discovery-report.preview.md`
- `qa-report.preview.md`

`artifact-preview.md` 固定表示候选索引，不能作为某个 artifact 的正文名称。

## 正式产物

正式产物固定使用：

- `requirement-analysis.md`
- `testcases.md`
- `api-test-draft.md`
- `ui-test-draft.md`
- `api-discovery-report.md`
- `qa-report.md`

审核记录固定使用 `<artifact>.review.yml`；历史目录固定使用 `artifacts/history/<artifact>/`。

## 代码与配置

- Python 测试文件使用 `test_*.py`。
- Workflow DSL 文件使用 `<workflow-id>.workflow.yml`，可执行 Workflow 只放在 `workflows/runtime/`。
- Prompt 文件使用 `<task>-prompt.md`；一个任务只保留一个 Prompt 正文。
- Markdown 文件使用小写字母和连字符。

## 禁止项

- 禁止 `workspace.yml`、`test-cases.md`、`qa-review.md` 等旧名称。
- 禁止使用 `new.md`、`tmp.py`、`final2.md` 等含义不清的名称。
- 禁止使用 `*-v2.md`、`*-v3.md` 在正式目录手工维护版本；版本由 promote 写入 `artifacts/history/` 和索引。
- 禁止为旧命名增加别名、双写、fallback 或兼容读取。
