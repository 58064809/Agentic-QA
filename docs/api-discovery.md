# API Discovery

`api_discovery_report` 基于 Playwright 网络抓包或 HAR 离线文件生成接口发现报告。第一版只支持离线解析，不启动浏览器。

## 输入

- `input/network-capture.har`
- `input/network-capture.json`
- `runs/<run_id>/network-capture.har`
- `runs/<run_id>/network-capture.json`

## 输出

- 候选产物：`runs/<run_id>/artifact-preview.md`
- 正式产物：`artifacts/api-discovery-report.md`

## 报告内容

- 采集来源
- 接口调用链
- 业务接口候选清单
- 请求/响应结构摘要
- 与 Swagger / Apifox 契约的关系
- 可转入 api-test-draft 的测试建议
- 脱敏说明
- 待确认问题

## 安全规则

- 抓包结果不是完整接口契约。
- 不保存真实 Authorization、Cookie、token 或 PII。
- 默认不保存完整 response body，只保存 schema 摘要。
- 不默认连接任何未授权环境；执行环境必须由输入文件和运行配置显式指定。
