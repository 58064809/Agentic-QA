# API Discovery Prompt

基于 Playwright network capture / HAR 离线文件生成接口发现报告。

## 规则

- 抓包结果只是运行时流量证据，不是完整接口契约。
- 必须脱敏 Authorization、Cookie、Set-Cookie、token、session 和 PII。
- 默认不保存完整 response body，只保留 schema 摘要。
- 过滤静态资源，合并重复接口，统计调用次数和状态码。
- 不默认连接任何未授权环境，不启动浏览器。
