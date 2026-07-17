# 配置

Harness 使用一个由调用方注入的 `ModelGateway`，不做按 Agent 或复杂度路由。凭证由具体
网关从进程环境或安全凭证提供方读取，不得写入 YAML、事件、tool-call 记录或产物。

MCP server 配置只允许 stdio 和 streamable HTTP，并必须声明 server/tool allowlist。
运行初始化后冻结 namespaced tool snapshot；本次 run 不接受服务器动态新增工具。
