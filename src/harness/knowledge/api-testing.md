# API 测试方法

只有完整 OpenAPI 可以确认 endpoint、方法、参数和响应 Schema；Markdown、抓包或残缺契约
只能形成 partial/missing 发现。设计 API 用例时覆盖认证授权、必填与类型、边界、错误码、
幂等、分页、并发、限流、超时和状态副作用。

机器用例必须符合 `agentic-qa.api-cases.v1.1`，请求位于 `request.method/path`，断言使用
类型化 `assertions`。默认不写入真实 token、Cookie 或生产地址；状态变更必须同时满足测试
环境和 execution profile 的方法 allowlist。
