# 读取测试管理资产

## 场景

项目已有 TestRail 或 Qase 测试资产时，需求分析、测试设计和 QA 报告阶段可以读取其中的项目、套件与
用例信息。连接器只提供查询视图，适合参考既有覆盖、术语和历史断言。

外部系统返回的内容属于未受信任数据。Prompt 会把它与系统指令分开；工具运行时还会限制查询类型、
分页数量、响应体大小和来源地址。Review Gate、Candidate 质量判断和发布行为不受连接器控制。

## 配置

workspace 的 `workspace.yml` 只记录环境变量名称，不保存实际地址、用户名、API Key 或 Token。
每个 workspace 的 `test_management` 配置采用单 provider 结构。

### TestRail

```yaml
data_sources:
  test_management:
    provider: testrail
    schema_version: agentic-qa.harness.testrail-source.v1
    base_url_env: TESTRAIL_URL
    username_env: TESTRAIL_USER
    api_key_env: TESTRAIL_API_KEY
    timeout_seconds: 10
    max_items: 100
    max_response_bytes: 1048576
```

当前 PowerShell 会话提供实际值：

```powershell
$env:TESTRAIL_URL = "https://example.testrail.io"
$env:TESTRAIL_USER = "qa@example.com"
$env:TESTRAIL_API_KEY = "<TestRail API Key>"
```

### Qase

```yaml
data_sources:
  test_management:
    provider: qase
    schema_version: agentic-qa.harness.qase-source.v1
    base_url_env: QASE_URL
    api_token_env: QASE_API_TOKEN
    timeout_seconds: 10
    max_items: 100
    max_response_bytes: 1048576
```

当前 PowerShell 会话提供实际值：

```powershell
$env:QASE_URL = "https://api.qase.io"
$env:QASE_API_TOKEN = "<Qase API Token>"
```

连接器接受 HTTPS 地址；含 URL 用户信息、query 或 fragment 的地址会在配置验证阶段被拒绝。凭据在
发起请求时从环境读取，不会进入 workspace、Prompt、工具参数或产物。Qase 的端点和分页边界以
[Qase 官方 API 文档](https://developers.qase.io/reference/introduction-to-the-qase-api)为依据。

## 固定查询

`test_management.read` 不接受任意 URL、HTTP 方法或路径。可用参数由 workspace 配置的 provider
决定：

| 查询 | TestRail 参数 | Qase 参数 | 返回内容 |
|---|---|---|---|
| `list_projects` | 无 | 无 | 可见项目 |
| `list_suites` | `project_id` | `project_code` | 项目中的测试套件 |
| `list_sections` | `project_id`，可选 `suite_id` | 不支持，明确拒绝 | TestRail 测试章节 |
| `list_cases` | `project_id`，可选 `suite_id`、`section_id` | `project_code`，可选 `suite_id` | 测试用例 |
| `get_case` | `case_id` | `project_code`、`case_id` | 单条测试用例 |

TestRail 单页最多返回 250 条，Qase 单页最多返回 100 条。两种 provider 都拒绝重定向，避免认证凭据
被带到其他地址；响应中的常见凭据字段和文本模式在写入 run 工具记录前会脱敏。

每次完成的读取都会写入当前 run 的 `tool-calls/`。相同幂等键会复用已记录结果，因此同一次模型步骤
不会因远端数据变化而重复取值。

## 示例

读取 TestRail 用例：

```json
{
  "operation": "list_cases",
  "project_id": 7,
  "suite_id": 3,
  "section_id": 12,
  "limit": 100,
  "offset": 0
}
```

读取 Qase 用例：

```json
{
  "operation": "list_cases",
  "project_code": "AUTH",
  "suite_id": 3,
  "limit": 100,
  "offset": 0
}
```

返回值包含 provider、固定资源名、记录列表和分页状态，不包含认证信息。既有测试资产可以帮助发现
覆盖缺口，但不会替代冻结需求来源，也不会自动成为 confirmed 需求事实。

## 常见问题

| 现象 | 系统行为 |
|---|---|
| workspace 没有连接器配置 | 工具返回未配置错误 |
| provider 不受支持 | 工具明确拒绝，不回退到其他 provider |
| 环境变量缺失 | 错误只列出缺失的变量名 |
| provider 返回 3xx | 请求停止，不跟随重定向 |
| 响应超过配置上限 | 本次读取失败，超量内容不写入 run |
| API 返回非 UTF-8 JSON 或异常结构 | 本次读取失败并记录结构化工具错误 |
| Qase 调用 `list_sections` | 明确拒绝；不会把 suite 静默解释成 section |
| 需要写回或更新用例 | 当前连接器没有写能力，外部测试管理系统保持不变 |
