# 配置参考

`.env.example` 是变量名清单，CLI 不自动加载 `.env`。真实值通过当前 shell、Windows 用户环境变量
或密钥管理服务注入。敏感值进入 workspace、Prompt、事件或产物时，安全扫描会报告问题。

## 环境变量

### 模型

| 变量 | 默认/状态 | 消费方式 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | 默认 DeepSeek 密钥 |
| `OPENAI_API_KEY` | 空 | 未选择 DeepSeek 且存在该值时使用 |
| `AGENTIC_QA_MODEL_API_KEY_ENV` | 自动选择 | 指定实际密钥变量名，不是密钥值 |
| `AGENTIC_QA_MODEL` | 空 | 同时覆盖 Flash/Pro 模型 |
| `AGENTIC_QA_MODEL_FLASH` | `deepseek-v4-flash` | Flash 路由模型 |
| `AGENTIC_QA_MODEL_PRO` | `deepseek-v4-pro` | Pro 路由模型 |
| `AGENTIC_QA_MODEL_BASE_URL` | DeepSeek 时 `https://api.deepseek.com` | OpenAI-compatible 地址 |
| `AGENTIC_QA_MODEL_TIMEOUT_SECONDS` | `180` | 模型请求超时秒数 |
| `AGENTIC_QA_MODEL_MAX_OUTPUT_TOKENS` | `16384` | 单次结构化产物最大输出 token；避免长用例 JSON 被默认上限截断 |

### Execution、RAG 与预留变量

| 变量 | 默认/状态 | 消费方式 |
|---|---|---|
| `AGENTIC_QA_BASE_URL` | 空 | ExecutionProfile 指定该变量名后，API 执行器读取地址 |
| `RAG_API_KEY` | 空 | 远程 embedding Provider 密钥 |
| `AGENTIC_QA_RAG_API_KEY_ENV` | `RAG_API_KEY` | 指定 RAG 实际密钥变量名 |
| `AGENTIC_QA_RAG_BASE_URL` | 空 | OpenAI-compatible embedding 地址 |
| `GITHUB_TOKEN` | 预留 | 当前运行时没有 GitHub MCP adapter，不读取 |
| `AGENTIC_QA_GITHUB_TOKEN_ENV` | 预留 | 当前运行时不读取 |

### PostgreSQL

| 变量 | 默认 | 用途 |
|---|---|---|
| `PG_LOCAL_HOST` | `localhost` | Checkpoint 与可选只读数据源主机 |
| `PG_LOCAL_PORT` | `5432` | 端口 |
| `PG_LOCAL_DATABASE` | `postgres` | 数据库 |
| `PG_LOCAL_USER` | `postgres` | 用户 |
| `PG_LOCAL_PASSWORD` | 无，必填 | 密码，只从环境读取 |

Checkpoint 与 `postgres.query` 使用独立配置类型，但默认引用同一组环境变量。生产运行不提供 SQLite
或内存 fallback。

## workspace.yml

`workspace create` 生成：

```yaml
schema_version: agentic-qa.harness.workspace.v2
id: demo
created_at: 2026-07-23T00:00:00+00:00
quality_policies: []
rag:
  provider: local-lexical
execution:
  environments: {}
```

`created_at` 由系统写入。业务策略使用注册名，例如 `city-opening-rewards`；未知、重复名称或
Python import path 会被配置校验拒绝。

### 注册测试环境

```yaml
execution:
  environments:
    qa:
      base_url_env: AGENTIC_QA_BASE_URL
      allowed_http_methods: [GET, HEAD, OPTIONS, POST]
      allow_ui_mutations: false
      max_request_timeout_seconds: 10
```

非 `analysis-only` 的 ExecutionProfile 会匹配环境名和 `base_url_env`，并与 workspace 的方法、
UI mutation 和超时上限比较。production-like 环境名被拒绝。

### RAG Provider

```yaml
rag:
  provider: openai-compatible
  api_key_env: RAG_API_KEY
  base_url_env: AGENTIC_QA_RAG_BASE_URL
  model: text-embedding-3-small
  chunk_size: 1200
  chunk_overlap: 400
```

`local-lexical` 不需要 API Key，也不外发 source。远程 Provider 缺少密钥时明确失败，不自动回退。

### 只读 PostgreSQL 数据源

```yaml
data_sources:
  postgres:
    schema_version: agentic-qa.harness.postgres-source.v2
    host_env: PG_LOCAL_HOST
    port_env: PG_LOCAL_PORT
    database_env: PG_LOCAL_DATABASE
    user_env: PG_LOCAL_USER
    password_env: PG_LOCAL_PASSWORD
    connect_timeout_seconds: 5
    statement_timeout_ms: 10000
    max_rows: 200
```

`postgres.query` 只接受单条 `SELECT/WITH`，使用只读事务，并限制超时与结果行数。

### 只读 TestRail 测试资产

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

配置保存环境变量名称，实际地址和凭据由当前进程环境提供。连接器查询固定的 TestRail 项目、套件、
章节和用例资源；完整场景和返回行为见[读取 TestRail 测试资产](test-management.md)。

## Source 摄取限制

| 边界 | 默认值 | 超限行为 |
|---|---:|---|
| 文件数 | 256 | 记录结构化 issue，停止继续纳入 |
| 相对路径 | 1024 UTF-8 bytes | 拒绝该路径 |
| 单文件解析预算 | 16 MiB | 完整流式 Hash，但不解析正文 |
| 单文件 Hash 预算 | 64 MiB | 不计算伪造的部分 Hash，标记 unavailable |
| 总 Hash 预算 | 64 MiB | 后续超预算文件标记 unavailable |
| 解析文本总量 | 100,000 characters | 保存截断快照并标记 partial |

Source 摄取器只解析 `workspace/sources` 内的相对普通文件。链接、junction、Windows reparse point、
绝对路径、`..`、控制字符和大小写折叠冲突均被拒绝；archive 不解压，Markdown/HTML/YAML 内容
不会执行。

通用策略允许 empty SourceBundle。是否要求来源或完整来源由启用的 QualityStrategy 声明；
`city-opening-rewards` 两者都要求。

## AgentRequest 与 MCP

AgentRequest 不从环境变量读取来源根。组合根会自动创建并允许项目内的
`local-sources/requirements/`；该目录整体由 Git 忽略。项目外来源通过可重复参数显式追加：

```powershell
python -m harness mcp serve `
  --allow-source-root D:\OpenAPI
```

默认根由 `--repo-root` 决定，追加允许根只存在于当前进程参数中，不写入 workspace；工具参数超出
白名单时返回权限错误。AgentRequest 固定使用 `analysis-only`，协议中没有 ExecutionProfile 字段。完整协议见
[跨 AI 接入](agent-integration.md)。
## 声明式质量策略

可扩展业务质量约束使用 `agentic-qa.declarative-quality-policy.v1` manifest，支持
`required_rules`、`boundary_requirements` 和 `forbidden_inventions`。内置示例位于
`src/harness/manifests/quality/city-opening-rewards.yml`，注册名为
`city-opening-rewards`。该默认名称由声明式 manifest 注册，不再加载同名的 Python
业务规则实现。

```yaml
quality_policies: [city-opening-rewards]
```

新增业务 Pack 应优先新增声明式 manifest，不应把具体业务文案、页面、接口或数据库细节写入
Python Validator。约束配置会进入 assessment identity 和质量报告。
