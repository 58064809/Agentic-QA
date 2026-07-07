# 接口自动化 YAML 用例生成

## 目标

将 PRD、Swagger / OpenAPI、业务规则和 RAG 检索上下文转化为可人工审核的 YAML 接口自动化用例草稿。草稿通过 Review Gate 后，才允许交给现有 pytest 框架执行。

## 输入

| 输入 | 说明 |
|---|---|
| PRD | 业务目标、流程、规则、权限和待确认项 |
| Swagger / OpenAPI / Apifox | 接口路径、方法、字段、响应结构、错误码和鉴权 |
| 业务规则 | 条件、动作、结果、状态流转和风控规则 |
| 数据库知识 | 状态字段、唯一约束、枚举和数据一致性观察点 |
| 自动化规范 | YAML schema、断言规则、变量提取和安全约束 |
| 历史经验 | 历史缺陷、漏测点、误报原因和回归风险 |

## 输出

候选 YAML 用例草稿默认写入运行目录，例如：

```text
prd/<id>/runs/<run_id>/api-test-cases.yml
```

输出必须满足：

- 顶层 `status: needs_human_review`。
- 顶层 `human_review_required: true`。
- 每条用例必须包含 `source_refs`。
- 接口路径只能写相对路径，不能写完整域名。
- 账号、密码、token、Cookie、动态 ID 只能使用变量或环境占位。
- 必须包含 `review_questions`，列出待人工确认项。

## 用例最小字段

每条用例至少包含：

| 字段 | 说明 |
|---|---|
| `id` | 用例 ID |
| `title` | 用例标题 |
| `priority` | `P0`、`P1`、`P2`、`P3` |
| `source_refs` | 来源引用，不能为空 |
| `request` | method、path、headers、query、body |
| `assertions` | HTTP、业务码、字段、状态或数据库观察点 |
| `variables` | 前置变量、提取变量或环境变量 |
| `review_status` | 默认 `needs_human_review` |

完整格式见 `knowledge/automation/yaml-case-schema.md`。

## Review Gate

AI 生成的 YAML 只表示候选草稿，不得绕过人工确认。人工至少需要确认：

- 接口路径、方法、字段、错误码是否与 Swagger / Apifox 一致。
- 业务规则、权限、风控和幂等预期是否正确。
- 测试账号、测试数据、环境和风险是否允许执行。
- 断言是否会误伤不稳定字段，例如时间戳、随机 ID、异步状态。

## 与 pytest 执行框架的边界

现有 pytest 执行框架只消费已确认或明确授权的 YAML 文件。没有显式环境变量和执行授权时，测试应跳过，不应请求真实服务。

推荐执行前置条件：

- `AGENTIC_QA_API_CASES_FILE` 指向经人工确认的 YAML 文件。
- `AGENTIC_QA_BASE_URL` 指向授权测试环境。
- 账号、token、租户、动态数据通过环境变量或 fixture 注入。
