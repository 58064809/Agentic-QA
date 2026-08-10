# 测试管理来源

TestRail 与 Qase 是只读测试资产来源。地址和凭据统一写在仓库根目录
`agentic-qa.local.yml`，不再写入 `workspace.yml`，也不再通过环境变量名间接引用。

## TestRail

```yaml
test_management:
  provider: testrail
  base_url: https://example.testrail.io
  username: qa@example.com
  api_key: local-value
  timeout_seconds: 10
  max_items: 250
  max_response_bytes: 1048576
```

## Qase

```yaml
test_management:
  provider: qase
  base_url: https://api.qase.io
  api_token: local-value
  timeout_seconds: 10
  max_items: 100
  max_response_bytes: 1048576
```

不用连接器时配置 `provider: none`。配置缺项或 URL 不是无凭据的 HTTPS 地址时，`config doctor` 在
网络调用前失败。

## 只读边界

| 查询 | TestRail 参数 | Qase 参数 |
|---|---|---|
| `list_projects` | 无 | 无 |
| `list_suites` | `project_id` | `project_code` |
| `list_sections` | `project_id`，可选 `suite_id` | 不支持 |
| `list_cases` | `project_id`，可选 suite/section | `project_code`，可选 `suite_id` |
| `get_case` | `case_id` | `project_code + case_id` |

连接器只发送固定 GET 请求、拒绝重定向、限制分页和响应大小。凭据从 Prompt、workspace、工具记录和
生成产物中排除；外部返回作为未受信任内容接受脱敏和校验。
