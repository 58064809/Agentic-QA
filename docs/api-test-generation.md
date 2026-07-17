# API 测试契约

API 机器用例只接受 `agentic-qa.api-cases.v1.1`。请求 method/path 位于
`request.method` 和 `request.path`，断言使用类型化 `assertions`。

只有完整且成功解析的 OpenAPI 可将 endpoint 标记为 confirmed。Markdown、抓包和不完整
契约只能生成 partial 或 missing，并必须带 source ref 和待确认项。状态变更方法只能在
execution profile 明确允许的测试环境中执行；base URL 和凭证不得写入产物。
