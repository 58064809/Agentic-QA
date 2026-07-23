# API 测试契约

API 机器用例 Schema 固定为 `agentic-qa.api-cases.v1.1`，独立于 Harness v2 控制面。

## 来源可信度

| 来源 | endpoint 事实 | 可生成内容 | 必须标记 |
|---|---|---|---|
| 完整且成功解析的 OpenAPI | confirmed | method/path、参数、响应 Schema、契约断言 | source ref |
| 残缺或解析失败的 OpenAPI | partial/missing | 缺口与待确认草案 | 解析问题 |
| Markdown/PRD | 不能确认协议事实 | 业务场景、规则候选 | 待确认 endpoint |
| 抓包/示例请求 | 只能作为观察样本 | 候选值与复现线索 | 非完整契约 |

请求位于 `request.method/path`，断言使用类型化 `assertions`。完整字段约束见机器可读
[API Cases JSON Schema](schemas/api-cases.v1.1.schema.json)。

## 执行边界

| 边界 | 要求 |
|---|---|
| 环境 | workspace policy 与 ExecutionProfile 双重授权，禁止 production-like 名称 |
| 地址 | `base_url_env` 指向的环境变量，不写入产物 |
| 凭证 | 仅环境变量或受控 fixture，输出必须脱敏 |
| 状态变更 | 方法必须同时在 workspace 与 run profile allowlist |
| 失败分类 | error/blocked 不自动转换为已确认 Bug |

不得用推测补齐 endpoint、响应、字段或业务规则。
