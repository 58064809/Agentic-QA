# 配置说明

## Source 摄取限制

每个 run 启动时建立不可变 SourceBundle。默认最多读取 256 个 regular files；相对路径最多
1024 UTF-8 bytes；单文件完整读取/哈希上限 16 MiB；总读取/哈希预算 64 MiB；解析文本总量
100,000 characters。链接、junction 和 Windows reparse point 不会被跟随，archive 不会解压，
Markdown、HTML 和 YAML 内容不会执行。

读取失败、非 UTF-8 和解析截断产生结构化 warning。是否要求来源由质量策略声明：通用策略允许
空 sources；`city-opening-rewards` 要求来源存在且完整。关键的配置、档位、对应关系、规则表或枚举
章节为空时产生 `suspected_missing_structure` blocker。

复制 `.env.example` 后只在本机环境或密钥管理服务中填写真实值。代码、workspace、Prompt、事件
和产物都不得保存 Token、API Key、Cookie 或数据库密码。

## 环境变量

| 变量 | 用途 | 默认行为 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 模型密钥 | 未配置时必须显式注入 ModelGateway |
| `AGENTIC_QA_MODEL_API_KEY_ENV` | 模型密钥变量名 | `DEEPSEEK_API_KEY` |
| `AGENTIC_QA_MODEL_FLASH` / `AGENTIC_QA_MODEL_PRO` | 模型路由 | DeepSeek Flash/Pro |
| `AGENTIC_QA_MODEL_BASE_URL` | OpenAI-compatible 模型地址 | `https://api.deepseek.com` |
| `AGENTIC_QA_BASE_URL` | 明确测试环境的 API 地址 | analysis-only 不读取 |
| `GITHUB_TOKEN` | GitHub MCP Token | 未启用 GitHub MCP 时不读取 |
| `AGENTIC_QA_GITHUB_TOKEN_ENV` | GitHub Token 变量名 | `GITHUB_TOKEN` |
| `RAG_API_KEY` | 远程 embedding Provider 密钥 | 本地词法 RAG 不读取 |
| `AGENTIC_QA_RAG_API_KEY_ENV` | RAG 密钥变量名 | `RAG_API_KEY` |
| `AGENTIC_QA_RAG_BASE_URL` | OpenAI-compatible embedding 地址 | 远程 RAG 才读取 |
| `PG_LOCAL_HOST/PORT/DATABASE/USER` | PostgreSQL 连接信息 | `localhost:5432/postgres/postgres` |
| `PG_LOCAL_PASSWORD` | PostgreSQL 密码 | 必填且只从环境变量读取 |

`.env.example` 中的敏感值使用空值占位，不应提交真实值。

## workspace.yml

新 workspace 使用 `agentic-qa.harness.workspace.v2`。默认只启用本地词法 RAG 和通用质量策略：

```yaml
schema_version: agentic-qa.harness.workspace.v2
id: demo
quality_policies: []
rag:
  provider: local-lexical
execution:
  environments: {}
```

业务质量策略只能按注册名选择，例如 `city-opening-rewards`；未知或重复名称会在创建 workspace
时拒绝。远程 RAG 可配置 `provider: openai-compatible`、模型与环境变量名，但不得内嵌密钥。

非 analysis-only 执行必须先在 `execution.environments` 登记 `base_url_env`、允许的 HTTP 方法、
UI mutation 和最大超时；`ExecutionProfile` 只能申请其子集，不能扩大权限。

## PostgreSQL

LangGraph checkpoint 与 `postgres.query` 测试数据源使用独立配置对象。checkpoint 固定从
`PG_LOCAL_*` 读取连接；测试数据源在 workspace 的 `data_sources.postgres` 中只登记环境变量名、
超时和结果上限。`postgres.query` 只允许单条 SELECT/WITH、只读事务和明确测试环境。
