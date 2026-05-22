# 状态规则

## 推荐合法状态

新生成或修订的 QA 产物默认使用以下状态。状态可以写入 `metadata.yml`，也可以写入产物 front matter。

| 状态 | 含义 |
|---|---|
| `needs_human_review` | AI 已生成或修改，等待人工评审，不得作为最终结论 |
| `reviewed` | 人工已打开并阅读，评审完成，但可能仍有待处理意见 |
| `needs_revision` | 人工评审后要求修改，Codex 应按评审意见增量修订 |
| `approved` | 人工确认通过，可作为后续任务输入 |
| `rejected` | 人工否决，需要重新生成、重做或废弃 |
| `archived` | 已归档，不再作为普通草稿覆盖 |

`draft` 只用于本地临时草稿或尚未进入仓库状态管理的内容；AI 写入 PRD 工作区的重要产物应直接进入 `needs_human_review`。

## 什么算评审或确认

以下情况才算人工评审或确认：

- 人工打开并阅读了对应产物。
- 用户在 Chat 中明确说“这版通过”“已评审”“按评审意见修改完成”“确认可以作为后续输入”。
- 产物 front matter 或 `metadata.yml` 中写入了状态、reviewer 和 review 时间。

以下情况不算人工评审或确认：

- 只是 AI 生成了文件。
- 只是说“看一下”“先放着”“感觉可以”，但没有明确通过或评审结论。
- 评审会上仍有待处理问题，且没有明确说明可作为后续输入。

建议 front matter：

```yaml
---
status: reviewed
artifact_type: requirement_analysis
human_review_required: false
reviewed_by: user
reviewed_at: 2026-05-22
review_notes: 已完成产品评审，待补充 xxx 规则
---
```

## 覆盖、增量和版本化

| 当前状态 | 允许动作 |
|---|---|
| `needs_human_review` | 允许覆盖草稿，但应说明覆盖原因 |
| `needs_revision` | 允许按评审意见增量修订，不建议整份重写 |
| `reviewed` | 默认只做增量修订，必须保留评审意见 |
| `approved` | 禁止直接覆盖，只能追加补充或新建版本 |
| `rejected` | 可重新生成新草稿，但应保留被拒绝原因 |
| `archived` | 禁止普通任务覆盖，需新版本或新 PRD 工作区 |

重新生成对比版时，使用 `*-v2.md`，或复制新的 PRD 工作区。

```text
评审前：可以覆盖草稿
评审后：优先增量修订
确认通过后：禁止覆盖，只能新版本或补充文件
```

## 推荐状态流转

```text
needs_human_review -> reviewed -> approved
needs_human_review -> reviewed -> needs_revision -> needs_human_review
needs_human_review -> rejected
approved -> archived
```

执行结果、失败分析、缺陷草稿和 QA 报告也先进入 `needs_human_review`。人工确认事实成立并允许进入后续任务时，再标记为 `approved`。

## 兼容旧状态

旧产物或旧脚本中可能仍出现以下状态：

| 旧状态 | 新口径 |
|---|---|
| `needs_changes` | `needs_revision` |
| `needs_human_confirmation` | `needs_human_review` |
| `confirmed` | `approved` |

Codex 处理旧状态时应按新口径解释，但不得擅自把旧状态批量改为通过状态。归档前必须确认工作区不存在待审、待确认、待修订或被拒绝状态。

## 确认权限

- 产品负责人确认需求理解、业务规则和待澄清问题。
- QA 负责人确认测试用例、执行范围、失败分类和报告结论。
- 开发或接口负责人确认接口契约、错误码和缺陷可复现性。
- Codex 只能建议状态，不能把审核门从待审改为通过，除非用户明确给出人工确认。
