# API Discovery

API Discovery 把 Web、H5 或后台页面的网络抓包整理成可审核的接口观察报告。首版读取已有
HAR 或简化 JSON；Playwright 在线监听与自动导出 HAR 尚未接入 Harness。

## 场景

当接口资料先出现在 UI 流程的浏览器流量中，而完整 OpenAPI 尚未提供时，
`api_discovery_report` 可以回答：

- 这次抓包观察到了哪些非静态网络调用；
- 哪些调用像业务接口，出现了几次、返回过哪些状态码；
- request/response 出现过哪些 JSON 字段和类型；
- 哪些敏感 header、query 或 body 字段已被脱敏；
- 哪些事实仍需与 OpenAPI、Swagger 或其他正式协议来源核对。

抓包表示一次或多次运行时观察，不代表完整 API 契约。其证据范围不包含字段必填性、枚举全集、
错误码全集、权限、风控或未执行到的业务分支。

## 操作

HAR 或简化 JSON 位于 workspace 的 `sources/` 后，run 选择
`api_discovery_report`：

```powershell
Copy-Item D:\Captures\benefits.har .\workspaces\demo\sources\network-capture.har

$result = python -m harness run start demo "基于冻结抓包生成接口发现报告" `
  --artifact api_discovery_report |
  ConvertFrom-Json
```

简化 JSON 接受顶层数组，或包含 `entries`、`calls`、`requests` 数组的对象。单条记录可以包含
`method`、`url`、`status`、`resource_type`、`duration_ms`、`request_headers`、
`response_headers`、`request_body`、`response_body` 和 `page_url`。

```json
{
  "entries": [
    {
      "method": "POST",
      "url": "https://test.example/api/assist?activity_id=demo",
      "status": 200,
      "resource_type": "xhr",
      "duration_ms": 28,
      "request_body": {"user_id": "example"},
      "response_body": {"accepted": true}
    }
  ]
}
```

## 系统响应

`network.capture.inspect` 只读取本次 run 的冻结 SourceBundle。系统过滤常见静态资源，去掉
origin 和 query value，把数字、UUID 等动态路径段归一化为 `{id}`，再按 method/path 合并重复
调用。

报告不会保存原始 header 值、query value、request body value 或完整 response body。body 只
留下字段名与 JSON 类型摘要；Authorization、Cookie、Set-Cookie、token、session 和常见 PII
字段会出现在脱敏清单中，不出现原值。

正常生成停在 `needs_human_review`，Candidate 位于：

```text
workspaces/<workspace>/candidates/<run_id>/api_discovery_report/raw.md
```

人工审核并选择通过质量门的版本后，发布视图位于：

```text
workspaces/<workspace>/published/api_discovery_report/current.md
```

报告中的候选证据类型固定为 `playwright-network-capture / observed`。后续
`api_test_draft` 可以据此形成待确认测试意图；在完整 OpenAPI 确认前，机器用例的
`contract_status` 保持未确认，method/path 为 `null`。

脱敏观察目录的数据结构见
[API Discovery JSON Schema](schemas/api-discovery.v1.schema.json)。该目录保存在本次 run 的
`network.capture.inspect` 工具记录中，Markdown Candidate 是它的确定性审核视图。

## 报告内容

确定性渲染器输出以下部分：

1. 采集来源；
2. 接口调用链；
3. 业务接口候选清单；
4. 请求与响应结构摘要；
5. 与 OpenAPI 契约的关系；
6. 可转入 API 测试草稿的建议；
7. 脱敏说明；
8. 待确认问题。

抓包中没有 XHR、fetch、JSON 响应或 `/api/` 路径时，报告显示“未发现业务接口候选”，仍保留
采集来源和限制说明。

## 常见问题

| 现象 | 系统行为 |
|---|---|
| 文件不是合法 HAR/JSON | 工具记录解析错误，artifact validation 进入修订；耗尽后 Candidate 标记 partial |
| 文件在 run 启动后才加入 `sources/` | 本次冻结 SourceBundle 不包含该文件，工具返回来源错误 |
| HAR 超过 SourceBundle 解析预算 | 来源状态变为 unavailable 或 partial，完整 JSON 解析结束 |
| 抓包包含图片、脚本和字体 | 静态调用被过滤，不进入调用链 |
| 同一接口使用不同数字 ID | 路径归一化后合并，调用次数和状态码汇总 |
| 抓包包含 Token、Cookie 或手机号 | 原值不进入目录或 Markdown，仅记录脱敏位置和类型摘要 |
| 需要在线执行页面并监听网络 | 当前版本尚未提供该链路；Playwright MCP 仍用于已配置的浏览器工具调用 |
