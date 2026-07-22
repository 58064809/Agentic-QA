# API 测试契约

API 机器用例只接受 `agentic-qa.api-cases.v1.1`，该版本独立于 Harness v2 控制面。
请求 method/path 位于 `request.method` 和 `request.path`，断言使用类型化 `assertions`。

只有完整且成功解析的 OpenAPI 可以将 endpoint 标记为 confirmed。Markdown、抓包和不完整契约
只能产生 partial 或 missing，并必须携带 source ref 与待确认项。质量策略会校验 Schema、引用
可追踪性和证据真实性，不能用推测补齐 endpoint、响应或业务规则。

状态变更方法只允许在 workspace 与 `ExecutionProfile` 双重授权的测试环境中执行；base URL
和凭证只从环境变量读取，不写入产物。工具的 error/blocked 记录不能自动转成已确认 Bug。
