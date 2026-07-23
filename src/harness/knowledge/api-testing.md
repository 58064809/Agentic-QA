# API 测试方法

## 来源判定

| 来源 | 结论级别 |
|---|---|
| 完整且成功解析的 OpenAPI | 可确认 endpoint、method、参数和响应 Schema |
| Markdown、抓包、残缺契约 | 只能形成 partial/missing 与待确认项 |

## 覆盖清单

- 认证授权、必填与类型、边界、错误码。
- 幂等、分页、并发、限流、超时和状态副作用。
- 请求使用 `request.method/path`，断言使用类型化 `assertions`。

## 输出与禁止

- 机器用例必须符合 `agentic-qa.api-cases.v1.1`。
- 不写入真实 Token、Cookie 或生产地址。
- 状态变更必须同时满足测试环境与 ExecutionProfile method allowlist。
