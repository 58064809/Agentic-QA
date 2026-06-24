# 自然语言驱动的确认机制

Agentic-QA 的确认机制不是人工手动修改文件，而是一个由自然语言触发的 **Review Gate Workflow**。

用户可以通过 AI 编辑器 Chat、飞书 Bot、微信 Bot、钉钉 Bot 或 CLI 表达确认、修改、驳回、继续执行等意图。Runtime 会通过 LangGraph interrupt 暂停工作流，等待外部入口用 `Command(resume=decision)` 恢复，并由确定性代码更新确认记录、运行记录和后续工作流状态。

## 确认工作流

```text
生成候选内容并通过质量检查
  ↓
human_review_node 调用 LangGraph interrupt
  ↓
工作流 checkpoint 暂停，run_status=interrupted
  ↓
Chat / Bot / CLI 收集用户确认意见
  ↓
外部入口构造 ReviewDecision
  ↓
Command(resume=decision)
  ↓
human_review_node 根据 action 更新 review_status 和 next_action
  ↓
approved 时写入候选 preview 与 reviews/*.review.yml
  ↓
等待独立 promote_artifacts
  ↓
promote_artifacts 成功后写入正式 artifacts/ 并标记 confirmed
```

interrupt payload 至少包含：

```yaml
run_id: ""
prd_path: ""
artifact_keys: []
review_status: needs_human_review
preview_path: ""
allowed_actions:
  - approve
  - reject
  - revise
```

resume decision 结构：

```yaml
action: approve
reviewed_by: ""
review_notes: ""
target_artifact: ""
```

多产物确认规则：

- 单产物场景可以省略 `target_artifact`，Runtime 自动使用唯一候选产物。
- 多产物 `approve` 必须明确 `target_artifact` 或 `all`。
- 多产物 `revise` 必须明确 `target_artifact` 或 `all`。
- 多产物 `reject` 可省略 `target_artifact`，Runtime 会按 `all` 记录。
- 非法 `target_artifact` 不允许进入 `approved` 或 `promote`。

## 确认意图类型

| 用户表达 | 识别意图 | 目标状态 | 后续动作 |
|---|---|---|---|
| “通过” / “确认” / “没问题” | `approve` | `approved` | `next_action=promote`，允许写候选 preview，等待确定性 promote |
| “确认并继续” / “继续生成接口测试” | `approve` | `approved` | 先完成当前候选产物确认，再由外部入口触发下游工作流 |
| “需要修改” / “补充xxx” | `revise` | `needs_changes` | `next_action=revise`，进入修订工作流 |
| “不通过” / “废弃” | `reject` | `rejected` | `next_action=stop`，停止复用当前产物 |
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
- `needs_human_review` 状态下，LangGraph 必须停在 interrupt checkpoint，不允许自动进入下游正式工作流。
- `needs_changes` 状态下，只允许进入修订工作流。
- `rejected` 状态下，不允许复用当前产物。
- `approved` 状态下，只表示候选产物通过 Review Gate，可以准备 promote；不能直接视为正式产物。
- `confirmed` 只能由 `promote_artifacts` 成功后设置；确认语义、LLM 或普通节点不能直接写 `confirmed`。
- `promote_artifacts` 是独立确定性函数，只能处理 `approved` review 记录，不能被 LLM 直接调用。
- 多产物场景必须明确目标产物，除非按规则显式使用或默认记录为 `all`。
- 所有确认动作必须记录原始用户输入、识别意图、确认决策、确认人、确认时间、意见和下一步动作。
- Chat / Bot / CLI 中的确认语义必须落到结构化确认记录，不能只停留在对话文本里。
