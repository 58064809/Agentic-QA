# 读取 TestRail 测试资产

## 场景

项目已有一批 TestRail 用例时，需求分析、测试设计和 QA 报告阶段可以读取其中的项目、套件、章节与
用例信息。连接器只提供查询视图，适合参考既有覆盖、术语和历史断言。

TestRail 返回的内容属于外部未受信任数据。Prompt 会把它与系统指令分开，工具运行时还会限制查询类型、
分页数量、响应体大小和来源地址。Review Gate、Candidate 质量判断和发布行为不受连接器控制。

## 配置

workspace 的 `workspace.yml` 记录环境变量名称，不保存实际地址、用户名或 API Key：

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

当前 PowerShell 会话可以提供对应值：

```powershell
$env:TESTRAIL_URL = "https://example.testrail.io"
$env:TESTRAIL_USER = "qa@example.com"
$env:TESTRAIL_API_KEY = "<TestRail API Key>"
```

地址使用 HTTPS，且不包含 URL 用户信息、query 或 fragment。实际凭据只在请求时从环境读取，不进入
workspace、Prompt、工具参数或产物。

## 系统响应

`test_management.read` 提供五种固定查询：

| 查询 | 标识参数 | 返回内容 |
|---|---|---|
| `list_projects` | 无 | 可见项目 |
| `list_suites` | `project_id` | 项目中的测试套件 |
| `list_sections` | `project_id`，可选 `suite_id` | 测试章节 |
| `list_cases` | `project_id`，可选 `suite_id`、`section_id` | 测试用例 |
| `get_case` | `case_id` | 单条测试用例 |

连接器只构造这些 TestRail GET 资源，不接受任意 URL、HTTP 方法或路径。分页一次最多返回 250 条；
重定向会被拒绝，避免 Basic Auth 凭据被带到其他地址。响应中的常见凭据字段和文本模式在写入 run
工具记录前会脱敏。

每次完成的读取都会写入当前 run 的 `tool-calls/`。相同幂等键会复用已记录结果，因此同一次模型步骤
不会因远端数据变化而重复取值。

## 示例

模型可见的工具调用参数类似：

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

返回值包含 provider、固定资源名、记录列表和分页状态；不会包含认证信息。既有 TestRail 用例可以
帮助发现覆盖缺口，但不会替代冻结需求来源，也不会自动成为 confirmed 需求事实。

## 常见问题

| 现象 | 系统行为 |
|---|---|
| workspace 没有连接器配置 | 工具返回未配置错误 |
| 环境变量缺失 | 错误只列出缺失的变量名 |
| TestRail 返回 3xx | 请求停止，不跟随重定向 |
| 响应超过配置上限 | 本次读取失败，超量内容不写入 run |
| API 返回非 UTF-8 JSON | 本次读取失败并记录结构化工具错误 |
| 需要写回或更新用例 | 当前连接器没有对应能力，外部 TestRail 保持不变 |
