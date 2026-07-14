# Agentic-QA 当前命令入口

自然语言是默认入口；`rag`、`resume`、`promote` 是本地调试和恢复命令。所有入口最终使用同一套 WorkflowSpec、Review Gate 和产物路径。

## 支持的生成意图

| intent | 示例 |
|---|---|
| `requirement_analysis` | “分析 prd/demo-requirement 的需求” |
| `testcase_generation` | “为 prd/demo-requirement 生成测试用例” |
| `analysis_and_testcases` | “分析 prd/demo-requirement 并生成测试用例” |
| `api_test_draft` | “基于接口文档生成 API 测试草稿” |
| `rag_automation_case_generation` | “用 RAG 生成 API YAML 自动化用例” |
| `ui_test_draft` | “生成 UI 自动化草稿” |
| `api_discovery_report` | “从 HAR 抓包生成接口发现报告” |
| `qa_report` | “生成 QA 报告草稿” |

未列出的 intent 会直接报错，不会回退到联合流程。

## 自然语言模式

```bash
python -m runtime.cli "分析 prd/demo-requirement 并生成测试用例"
```

需求来源可以是：

- 已存在的 `prd/<id>` 工作区；
- 本地 Markdown、PDF、DOCX、TXT 或 HTML；
- 飞书 docx/Wiki 链接；
- 直接输入的 Markdown 需求正文。

API 文档和 HAR/JSON 抓包路径可以放在同一条自然语言命令中；CLI 会先导入到目标工作区，再运行对应 WorkflowSpec。

生成成功的含义是候选产物已写入并等待审核，不代表正式发布。CLI 会显示“候选产物已生成，等待人工审核”，并给出 run id。

## Review Gate

首次生成会停在 LangGraph interrupt：

```text
review_status = needs_human_review
run_status = interrupted
next_action = wait_for_review
```

恢复审核：

```bash
python -m runtime.cli resume <run_id> "测试用例通过，发布正式产物"
```

支持的审核动作：

- approve：通过，进入 `approved`
- reject：驳回，进入 `rejected`
- revise：要求修改，进入 `needs_changes`
- show_diff / hold / clarify：保持 `needs_human_review`

多产物 run 的 approve/revise 必须明确 `requirement_analysis`、`testcases` 或 `all`。不明确时 Runtime 必须停止并提示选择。

自然语言“通过并发布”可以在一次交互中完成审核和发布，但内部仍是两个确定性阶段：Review Gate 先写 `approved`，promote 再写正式产物并标记 `confirmed`。

## 显式 promote

```bash
python -m runtime.cli promote prd/<requirement> [run_id] [artifact]
```

artifact 支持：

- `requirement_analysis`
- `testcases`
- `api_test_draft`
- `ui_test_draft`
- `api_discovery_report`
- `qa_report`

未给出 `run_id` 时读取 `prd/<id>/runs/latest.yml`。未给出 artifact 时读取该 run 实际记录的候选产物；运行记录没有声明候选产物时命令失败，不推断默认类型。

示例：

```bash
python -m runtime.cli promote prd/demo-requirement testcases
python -m runtime.cli promote prd/demo-requirement run-20260714-120000-abcd12 testcases
python -m runtime.cli promote prd/demo-requirement run-20260714-120000-abcd12 requirement_analysis
```

promote 只接受 `approved` review。成功后：

- 写入 `prd/<id>/artifacts/<artifact>.md`；
- 旧正式版本进入 `artifacts/history/`；
- review 变为 `confirmed`；
- 更新 metadata 和版本索引。

## RAG 调试

```bash
python -m runtime.cli rag status
python -m runtime.cli rag build
python -m runtime.cli rag search "边界值 活动规则"
```

这些命令只检查索引和检索，不生成 QA 产物。

## 工作区命令

```bash
python scripts/create_prd_workspace.py demo-requirement
python scripts/validate_prd_workspace.py prd/demo-requirement
```

标准输出位置：

| 内容 | 路径 |
|---|---|
| 候选预览 | `prd/<id>/runs/<run_id>/artifact-preview.md` |
| 候选结构化数据 | 同目录下 `.json` / `.yml` sidecar |
| 审核记录 | `prd/<id>/reviews/*.review.yml` |
| 正式产物 | `prd/<id>/artifacts/` |
| Runtime 记录 | `.runtime/runs/<run_id>/` |

## 验证命令

```bash
ruff check .
python scripts/validate_docs_consistency.py
pytest -q
```

`natural language mode` 与 `debug mode` 共用当前契约；调试命令不得引入另一套路径、状态或工作流。
