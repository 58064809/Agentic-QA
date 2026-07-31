# API Discovery

API Discovery 把 Web、H5 或后台页面的网络流量整理成可审核的接口观察报告。系统支持两种来源：
已有 HAR/简化 JSON，以及显式测试环境中的实时 Playwright MCP 会话。

实时链路直接把浏览器网络详情转换为脱敏强类型目录，不落盘原始 HAR。即使省略 response body，
header、Cookie 和请求内容仍可能进入 HAR，因此当前产品使用哈希绑定的脱敏目录提供可携带导出，
原始 HAR 不进入 Candidate 或 published。

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

### 已有抓包

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

### 实时 Playwright 会话

实时发现使用 workspace 中已登记的测试环境和 Playwright MCP。下面的配置创建隔离、无界面的
浏览器会话，阻断 service worker，并冻结页面动作与网络读取工具：

```yaml
execution:
  environments:
    qa:
      base_url_env: AGENTIC_QA_BASE_URL
      allowed_http_methods: [GET, HEAD, OPTIONS, POST]
      allow_ui_mutations: true
      max_request_timeout_seconds: 10
mcp:
  playwright:
    transport: stdio
    command: npx
    args:
      - -y
      - "@playwright/mcp@latest"
      - --isolated
      - --headless
      - --block-service-workers
    allowlist:
      - browser_navigate
      - browser_snapshot
      - browser_find
      - browser_click
      - browser_fill_form
      - browser_network_requests
      - browser_network_request
    request_timeout_seconds: 60
```

测试站点地址来自环境变量：

```powershell
$env:AGENTIC_QA_BASE_URL = "https://qa.example.test"
```

run 的 goal 描述页面动作，ExecutionProfile 选择同一个环境：

```powershell
$result = python -m harness run start demo `
  "打开活动页，完成一次助力流程并生成实时接口发现报告" `
  --artifact api_discovery_report `
  --environment qa `
  --base-url-env AGENTIC_QA_BASE_URL `
  --allow-http-method GET `
  --allow-http-method HEAD `
  --allow-http-method OPTIONS `
  --allow-http-method POST `
  --allow-ui-mutations |
  ConvertFrom-Json
```

缺少测试环境、base URL、UI mutation 授权、Playwright MCP 配置或两个网络工具时，run 在执行前或
工具调用阶段返回明确错误。`analysis-only` 不启动实时浏览器。

## 系统响应

`network.capture.inspect` 只读取本次 run 的冻结 SourceBundle；`network.capture.live` 只读取
本次受控 Playwright 会话。系统过滤常见静态资源，去掉 query value，把数字、UUID 和长 Token
路径段归一化为 `{id}`，再按 method/origin/path 合并重复调用。

实时任务向模型展示 allowlisted 页面动作和 `network.capture.live`。原始
`browser_network_requests`、`browser_network_request` 与任意服务器代码执行工具不进入模型
工具区。Harness 在内部读取网络详情，完成脱敏后才把强类型目录加入模型上下文和工具记录。

`browser_navigate` 与新建 tab 的 URL 会和 ExecutionProfile 指向的 base URL 比较 origin。最终
document 流量离开该 origin 时，实时采集返回权限错误。第三方 API 请求仍作为独立 origin 记录，
不会与测试站点上的同路径接口合并。

仓库 CI 中的 `playwright-mcp-live-smoke` job 使用本地临时 HTTP 服务和官方 Playwright MCP
进程验证这条链路。测试页面触发一条带模拟敏感字段的 POST 请求，CI 检查接口归一化、字段结构、
脱敏结果和 MCP 生命周期。该 job 不调用真实模型，也不访问业务测试环境。

报告不会保存原始 header 值、query value、request body value 或完整 response body。body 只
留下字段名与 JSON 类型摘要；Authorization、Cookie、Set-Cookie、token、session 和常见 PII
字段会出现在脱敏清单中，不出现原值。

正常生成停在 `needs_human_review`，Candidate 位于：

```text
workspaces/<workspace>/candidates/<run_id>/api_discovery_report/raw.md
workspaces/<workspace>/candidates/<run_id>/api_discovery_report/discovery-catalog.json
```

`discovery-catalog.json` 与 Markdown、质量报告一起写入 create-only Candidate manifest。审核选择
的强类型版本包含该附件的 SHA-256，因此附件发生变化时发布校验返回 hash 错误。

人工审核并选择通过质量门的版本后，发布视图和脱敏机器目录位于：

```text
workspaces/<workspace>/published/api_discovery_report/current.md
workspaces/<workspace>/published/api_discovery_report/current.catalog.json
```

报告中的候选证据类型固定为 `playwright-network-capture / observed`。后续
`api_test_draft` 可以据此形成待确认测试意图；在完整 OpenAPI 确认前，机器用例的
`contract_status` 保持未确认，method/path 为 `null`。

脱敏观察目录的数据结构见
[API Discovery JSON Schema](schemas/api-discovery.v1.1.schema.json)。离线目录保存在
`network.capture.inspect` 工具记录中，实时目录保存在 `network.capture.live` 工具记录中；
Markdown Candidate 是它的确定性审核视图。可携带导出的封装结构见
[API Discovery Export JSON Schema](schemas/api-discovery-export.v1.schema.json)。

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
| 实时任务没有 frozen HAR/JSON | 系统切换到显式测试环境中的 Playwright MCP 实时发现 |
| 页面跳转到不同 origin | 导航或采集阶段返回权限错误，不生成完成态 Candidate |
| Playwright allowlist 缺少网络工具 | 启动校验报告 `browser_network_requests` 与 `browser_network_request` 缺口 |
| 普通本地测试没有浏览器或 Node.js | live smoke 默认跳过；独立 CI job 显式安装并运行官方 MCP 浏览器 |
| 需要携带或接入下游系统 | Candidate 和 published 提供哈希绑定的 `discovery-catalog.json` |
| 需要原始 HAR 文件 | 原始 HAR 可能包含凭据和个人数据；系统不会把它加入 Candidate 或 published |
