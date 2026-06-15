# 自然语言驱动的确认机制

Agentic-QA 的确认机制不是人工手动修改文件，而是一个由自然语言触发的 **Review Gate Workflow**。

用户可以通过 AI 编辑器 Chat、飞书 Bot、微信 Bot、钉钉 Bot 或 CLI 表达确认、修改、驳回、继续执行等意图。Runtime 会通过意图识别将用户输入转换为结构化确认动作，并自动更新确认记录、运行记录和后续工作流状态。

## 确认工作流

```text
用户在 Chat / Bot / CLI 表达确认意见
  ↓
意图识别
  ↓
识别为审核 / 确认 / 修订 / 继续执行类任务
  ↓
解析目标产物
  ↓
解析确认决策
  ↓
解析修改意见或下一步动作
  ↓
工作流选择
  ↓
执行 Review Gate Workflow
  ↓
更新 reviews/*.review.yml
  ↓
写入 runs/<run-id>/events.jsonl
  ↓
触发下一步工作流或进入修订流程
```

## 确认意图类型

| 用户表达 | 识别意图 | 目标状态 | 后续动作 |
|---|---|---|---|
| “通过” / “确认” / “没问题” | `approve_artifact` | `approved` | 允许进入下一步 |
| “确认并继续” / “继续生成接口测试” | `approve_and_continue` | `approved` | 触发下游工作流 |
| “需要修改” / “补充xxx” | `request_changes` | `needs_changes` | 进入修订工作流 |
| “不通过” / “废弃” | `reject_artifact` | `rejected` | 停止复用当前产物 |
| “重新生成” | `regenerate_artifact` | `draft` | 触发重新生成流程 |
| “归档” | `archive_artifact` | `archived` | 写入归档索引 |

## 确认记录

```yaml
artifact: artifacts/testcases.md
artifact_type: testcases
status: needs_human_review
reviewer: ""
reviewed_at: null
decision: ""
comments: []
required_changes: []
approved_sections: []
rejected_sections: []
next_action: ""
source_message: ""
run_id: ""
```

## Review Gate 规则

- 用户确认动作必须通过意图识别进入 Review Gate Workflow。
- 不要求用户手动编辑 `reviews/*.review.yml`。
- 不要求用户手动维护产物状态。
- `needs_human_review` 状态下，不允许自动进入下游正式工作流。
- `needs_changes` 状态下，只允许进入修订工作流。
- `rejected` 状态下，不允许复用当前产物。
- `approved` 状态下，可以进入下一步生成流程。
- `confirmed` 状态下，可以归档，或作为正式知识资产进入 RAG。
- 所有确认动作必须记录原始用户输入、识别意图、确认决策、确认人、确认时间、意见和下一步动作。
- Chat / Bot / CLI 中的确认语义必须落到结构化确认记录，不能只停留在对话文本里。
