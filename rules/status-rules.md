# 状态规则

状态枚举以 `runtime/workspace.py.ALLOWED_ARTIFACT_STATUSES` 为程序事实源。Runtime、Review Gate、产物 Front Matter、review 记录和 `metadata.yml` 必须使用同一套状态，不保留旧状态别名。

## 当前状态

| 状态 | 含义 | 是否可作为正式资产 |
|---|---|---|
| `draft` | 生成中或尚未进入审核 | 否 |
| `partial` | 仅完成部分内容 | 否 |
| `needs_human_review` | 候选等待人工确认 | 否 |
| `approved` | 候选已批准，可执行 promote | 否，尚未 promote |
| `needs_changes` | 候选需要修订 | 否 |
| `rejected` | 候选被驳回 | 否 |
| `confirmed` | promote 成功后的当前正式版本 | 是 |
| `archived` | 已归档，不再是当前版本 | 否 |
| `failed` | 生成或处理失败 | 否 |
| `superseded` | 已被新版本替代 | 否 |

## 状态流转

```text
draft
  -> partial / failed
  -> needs_human_review
  -> approved / needs_changes / rejected
  -> approved + promote success
  -> confirmed
  -> superseded / archived
```

关键约束：

1. 生成完成只能进入 `needs_human_review`，不能直接进入 `approved` 或 `confirmed`。
2. `approved` 仅表示候选通过 Review Gate，正式文件尚未发布。
3. `confirmed` 只能由确定性 promote 成功后产生。
4. `needs_changes` 必须生成新候选或新 run，不能直接修改正式产物。
5. `rejected`、`partial`、`failed` 不得作为正式 RAG 知识输入。
6. 正式版本被替换后进入 `superseded` 或历史归档。

## 状态记录位置

- 候选 Front Matter：`runs/<run-id>/<artifact>.preview.md`
- 审核状态：`reviews/<artifact>.review.yml`
- 当前正式状态：`artifacts/<artifact>.md`
- 需求级汇总：`metadata.yml`
- 运行状态：PRD run pointer 与 `.runtime/runs/<run-id>/`

同一 artifact 的 review、metadata、候选和正式文件必须指向一致的 run_id、版本和状态。

## 人工确认

只有明确表达“通过、批准、发布正式产物”等确认语义，且 ReviewDecision 校验通过，才能把候选更新为 `approved`。

以下表达不能直接批准：

- “先看看”
- “感觉还行”
- “先不要发布”
- “暂时放着”
- 含义冲突或低置信度的反馈

LLM 只解析用户反馈，程序状态机负责裁决和写入。

## 禁止项

- 禁止 `reviewed`、`needs_revision`、`needs_human_confirmation` 等旧状态。
- 禁止把 `confirmed` 解释为 `approved` 的别名。
- 禁止用手工 `*-v2.md` 代替 history index。
- 禁止为旧状态增加兼容映射、fallback 或批量转换。
