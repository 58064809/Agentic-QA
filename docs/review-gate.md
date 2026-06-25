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
外部入口构造包含原始自然语言的 resume decision
  ↓
Command(resume=decision)
  ↓
human_review_node 调用 process_review_gate()
  ↓
ReviewDecision / 状态机校验 / reviews/*.review.yml 更新
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
  - show_diff
  - hold
  - clarify
```

resume decision 结构：

```yaml
action: approve
user_input: "测试用例通过，发布正式产物"
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
- `action` 只能作为外部入口的结构化提示；最终审核语义必须由 `process_review_gate()` 解析和校验。
- `human_review_node` 只负责 interrupt payload 与 resume payload 的基础合法性检查；Review 语义、target 归一化和状态迁移以 `process_review_gate()` 为准。

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
- CLI 自然语言确认和 LangGraph interrupt resume 必须复用同一套 `process_review_gate()` 语义。
- 所有确认动作必须记录原始用户输入、识别意图、确认决策、确认人、确认时间、意见和下一步动作。
- Chat / Bot / CLI 中的确认语义必须落到结构化确认记录，不能只停留在对话文本里。

## Debug Preview Write

`debug_approve_preview_write` 仅允许用于本地 debug / test 场景，用来跳过 interrupt 并写入 `runs/<run-id>/artifact-preview.md` 候选预览。

该开关不得作为生产 Review Gate 替代路径：

- 只能写候选 preview，不能写正式 `artifacts/`。
- 不能设置 `confirmed`。
- 不能生成 `approved` review 记录。
- `promote_artifacts` 必须继续拒绝没有 `approved` review 记录的 run。
- Chat / Bot / CLI 生产入口不得传入该开关。

## CLI Natural Publish

用户在 CLI 自然语言入口表达“通过并发布”时，Runtime 必须按状态拆成确定性步骤：

1. 如果存在 matching PRD 的 interrupted run，先用 `Command(resume=decision)` 恢复该 run，并走 `human_review_node -> process_review_gate()`。
2. resume 成功进入 `approved` 后，才允许调用独立 `promote_artifacts()` 发布正式产物。
3. 如果不存在 interrupted run，但已有 `approved` review 记录，可以直接执行 `promote_artifacts()`。
4. 如果 latest run 仍是 `needs_human_review`，必须先写入 Review Gate approve 记录，再执行 promote；不能绕过 Review Gate 直接发布。
5. “通过并发布”可以在一条 CLI 命令内完成，但运行记录中必须保留 approve/resume 与 promote 两个确定性阶段的痕迹。

如果自然语言发布请求没有明确目标 artifact，且当前 run 包含多个候选产物，CLI 必须进入 clarify，不得默认发布全部。提示必须包含候选产物列表，并要求用户选择“只发布测试用例”“只发布需求分析”或“全部发布”。
