# Agentic-QA 命令入口

`COMMANDS.md` 只定义用户如何发起任务，以及 CLI 的稳定调试入口。可执行流程以 `workflows/runtime/*.workflow.yml` 为准；产物路径以 `runtime/workspace.py` 为准；本文件不复制节点级实现细节。

## 入口原则

- Chat、Bot、CLI 和 API 使用同一套自然语言任务语义。
- Runtime 负责意图识别、PRD 工作区定位、Workflow 选择、上下文构建、生成、质量检查、Review Gate 和 promote。
- 生成任务只写 `prd/<id>/runs/<run-id>/<artifact>.preview.md` 候选正文。
- `prd/<id>/runs/<run-id>/artifact-preview.md` 只是候选索引。
- 未经 Review Gate 批准的候选产物不得进入 `prd/<id>/artifacts/`。
- 不支持旧目录、旧文件名或旧式子命令兼容。

## 自然语言任务

### 需求分析

```text
分析 prd/sample-login-requirement 的需求，识别业务规则、风险和待确认项。
```

目标候选：`runs/<run-id>/requirement-analysis.preview.md`。

### 测试用例生成

```text
基于 prd/sample-login-requirement 生成测试用例，覆盖主流程、异常、边界值和状态流转。
```

目标候选：`runs/<run-id>/testcases.preview.md`。

### 需求分析与测试用例

```text
分析 prd/sample-login-requirement 并生成测试用例。
```

同一 run 生成两个独立候选正文，并在 `artifact-preview.md` 中建立索引。

### API 测试草稿

```text
基于 prd/sample-login-requirement 的需求、接口契约和已确认测试用例生成 API 测试草稿。
```

目标候选：`runs/<run-id>/api-test-draft.preview.md`。

### UI 自动化草稿

```text
基于 prd/sample-login-requirement 生成 UI 自动化测试草稿。
```

目标候选：`runs/<run-id>/ui-test-draft.preview.md`。

### 接口发现报告

```text
根据 prd/sample-login-requirement 的 HAR 或网络抓包输入生成接口发现报告。
```

目标候选：`runs/<run-id>/api-discovery-report.preview.md`。

### QA 报告

```text
汇总 prd/sample-login-requirement 的已确认产物和执行证据，生成 QA 报告草稿。
```

目标候选：`runs/<run-id>/qa-report.preview.md`。

## Review Gate

### 批准并发布

```text
prd/sample-login-requirement 的测试用例通过，发布正式产物。
```

Runtime 必须依次完成：

1. 定位目标 PRD、run 和 artifact。
2. 将自然语言解析为结构化 `ReviewDecision`。
3. 更新对应 `reviews/<artifact>.review.yml` 为 `approved`。
4. 调用确定性 promote。
5. 写入 `artifacts/<artifact>.md`，归档旧版本并更新 `metadata.yml`。
6. promote 成功后将正式状态标记为 `confirmed`。

多产物 run 未明确目标时必须停止并要求选择单个产物或全部产物，禁止猜测。

### 要求修改

```text
测试用例不通过，补充支付失败、库存不足和优惠券失效场景。
```

该操作只更新 Review Gate 状态并触发新候选 run，不覆盖正式产物。

### 驳回

```text
驳回这版 API 测试草稿，接口范围识别错误，需要重新生成。
```

被驳回候选不得继续 promote，也不得作为正式 RAG 知识输入。

## CLI

### 自然语言入口

```bash
agentic-qa "分析 prd/demo-requirement 并生成测试用例"
python -m runtime.cli "分析 prd/demo-requirement 并生成测试用例"
```

### 恢复中断的 Review Gate

```bash
python -m runtime.cli resume <run-id> "测试用例通过，发布正式产物"
```

`resume` 必须使用原 `thread_id` 和 checkpoint 恢复工作流，不创建旧式旁路。

### 显式 promote

```bash
python -m runtime.cli promote prd/<id> [run-id] [artifact]
```

支持的 artifact key：

- `requirement_analysis`
- `testcases`
- `api_test_draft`
- `ui_test_draft`
- `api_discovery_report`
- `qa_report`

未指定 run 时读取 `runs/latest.yml`；未指定 artifact 且 run 包含多个候选时必须报错并要求明确选择。

### RAG 调试

```bash
python -m runtime.cli rag status
python -m runtime.cli rag build
python -m runtime.cli rag search "边界值 活动规则"
```

RAG 调试命令不生成 QA 产物。

### 工作区与仓库校验

```bash
python scripts/create_prd_workspace.py demo-requirement
python scripts/validate_prd_workspace.py prd/demo-requirement
python scripts/validate_docs_consistency.py
pytest
ruff check .
```

## 当前产物流转

```text
自然语言任务
  -> Workflow DSL
  -> 上下文与 RAG
  -> QA Agent 生成
  -> 质量检查
  -> 写入 runs/<run-id>/<artifact>.preview.md
  -> 写入 artifact-preview.md 索引和 runs/latest.yml
  -> Review Gate interrupt
  -> approve / needs_changes / rejected
  -> approved 后确定性 promote
  -> artifacts/<artifact>.md
  -> artifacts/history/<artifact>/
  -> metadata.yml
```

## 禁止项

- 直接写或覆盖 `artifacts/*.md`。
- 把生成完成视为审核通过。
- 跳过 Review Gate。
- 把 `artifact-preview.md` 当作多产物正文。
- 使用 `workspace.yml`、`analysis/`、`cases/`、`execution/`、`defects/`、`report/` 等旧链路。
- 为旧命令、旧路径或旧文件名增加兼容分支。

## Chat 完成回执

任务结束后的回复遵守 `rules/agent-output-rules.md`，只包含变更摘要、修改文件、验收结果、待人工确认和下一步建议；不粘贴完整大文件或完整 diff。
