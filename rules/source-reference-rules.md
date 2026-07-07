# 来源引用规则

## 目标

来源引用用于证明 AI 生成内容来自哪些需求、接口契约、业务规则或历史经验。接口自动化 YAML 用例必须逐条保留 `source_refs`，便于人工评审和后续追溯。

## source_refs 格式

每个来源引用建议包含：

| 字段 | 说明 |
|---|---|
| `source_type` | `prd`、`swagger`、`business_rule`、`db_rule`、`automation_rule`、`historical_lesson`、`inference` |
| `source_path` | 来源文件路径 |
| `chunk_id` | RAG chunk 标识 |
| `locator` | 章节、接口、字段、行号或规则编号 |
| `summary` | 与该用例相关的来源摘要 |
| `confidence` | `high`、`medium`、`low` |

## 引用要求

- 每条用例至少包含一个 `source_refs`。
- 接口路径、方法和字段优先引用 Swagger / OpenAPI 来源。
- 业务预期优先引用 PRD 或业务规则来源。
- 断言策略优先引用自动化规则或断言规则来源。
- 历史经验只能作为补充来源，不能作为唯一事实来源。

## 推断来源

当信息不足但仍需要生成草稿时，可以使用 `source_type: inference`，但必须同时满足：

- `confidence` 为 `low` 或 `medium`。
- 在 `summary` 中说明推断依据。
- 在 `review_questions` 中列出需要人工确认的问题。

## 禁止事项

- 不得写空的 `source_refs: []`。
- 不得把“常识”“经验上应该如此”当作确认来源。
- 不得引用不存在的文件路径。
- 不得引用敏感原文片段。
