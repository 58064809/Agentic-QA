# 10 Runtime 测试用例生成工作流

## 适用场景

用于第 2 阶段 LangGraph Runtime 的第一条闭环：根据 PRD 上下文、声明式 Workflow、Prompt、Rules、Skills 和 Knowledge 生成测试用例草稿。

## 触发命令

- “用 Runtime 生成测试用例。”
- “实现测试用例生成 Graph。”
- “基于 LangGraph 跑 `prd/<id>` 的测试用例生成流程。”

## 主流程

```text
intent_router_node
  ↓
workflow_selector_node
  ↓
context_loader_node
  ↓
testcase_generation_node
  ↓
testcase_quality_check_node
  ↓
条件判断：
  ├── pass → human_review_node
  └── fail → testcase_revision_node → testcase_quality_check_node
  ↓
artifact_writer_node
  ↓
metadata_update_node
```

## 节点定义

| 节点 | 责任 | 是否允许模型参与 |
|---|---|---|
| `intent_router_node` | 识别用户命令是否属于测试用例生成 | 否，优先确定性分类 |
| `workflow_selector_node` | 匹配 `workflows/02-testcase-generation-workflow.md` | 否 |
| `context_loader_node` | 加载 PRD、Prompt、Rules、Skills、Knowledge | 否 |
| `testcase_generation_node` | 生成测试用例草稿 | 是 |
| `testcase_quality_check_node` | 检查覆盖、格式、路径和审核状态 | 半 Agent，规则优先 |
| `testcase_revision_node` | 根据质量问题修正草稿 | 是 |
| `human_review_node` | 暂停并等待人工审核 | 否 |
| `artifact_writer_node` | 写入 `runs/<run_id>/cases/test-cases.md`，并更新 `runs/latest.yml`、`runs/index.jsonl` | 否 |
| `metadata_update_node` | 更新 metadata 或运行记录状态 | 否 |

## 输入状态

- 用户自然语言命令。
- 目标 PRD 工作区路径。
- `workspace.yml`。
- `input/requirement.md`。
- `input/api.md`。
- 已有 `analysis/requirement-analysis.md`。
- Runtime 当前运行记录。

## 输出状态

- 测试用例草稿内容。
- 质量检查结果。
- Human Review Gate 状态。
- 写入路径：`prd/<id>/runs/<run_id>/cases/test-cases.md`。
- metadata 或运行记录中的 `needs_human_review` 状态。

## 必须读取的文件

- `docs/production-agent-runtime-roadmap.md`
- `workflows/02-testcase-generation-workflow.md`
- `prompts/testcase-design-prompt.md`
- `rules/testcase-rules.md`
- `rules/review-gate-rules.md`
- `skills/test-design/test-design-skill.md`
- `knowledge/templates/testcase-template.md`
- `prd/<id>/workspace.yml`
- `prd/<id>/input/requirement.md`
- `prd/<id>/input/api.md`

## Human Review Gate

- Runtime 生成的测试用例必须停在 `needs_human_review`。
- 未经人工审核，不得继续生成自动化脚本。
- 人工审核意见必须写回运行记录或 metadata 对应状态。

## Artifact Writer 规则

- 只允许写入目标 PRD 工作区。
- 默认写入 `prd/<id>/runs/<run_id>/cases/test-cases.md`，并更新最新指针和历史索引。
- 不允许覆盖人工已审核内容，除非用户明确要求。
- 不允许把 Prompt、Rules、Skills 硬编码进 Runtime 代码。

## 状态更新规则

- 生成草稿后标记为 `needs_human_review`。
- 审核通过后才允许进入 API/UI 自动化脚本生成。
- 质量检查失败时进入 `testcase_revision_node`，不得直接写入正式结论。

## 验收标准

- Runtime 流程能读取现有声明式资产，而不是替代它们。
- 输出路径符合 `rules/artifact-path-rules.md`。
- 测试用例格式符合 `knowledge/templates/testcase-template.md`。
- Human Review Gate 明确阻断后续自动化生成。
- 运行结果可追踪、可复查、可恢复。
