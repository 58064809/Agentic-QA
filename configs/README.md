# Configs

`configs/` 是 Runtime 的统一配置入口。可提交文件只能是示例；真实本地配置和密钥不得提交。

## 加载顺序

Runtime 通过 `runtime.config.load_app_config()` 按以下顺序加载并合并配置：

1. `configs/config.yaml`
2. `configs/local.yaml`
3. `configs/private.yaml`

后加载的文件覆盖先加载的文件。环境变量仍由各模块作为最高优先级处理。

## 推荐用法

复制示例后按需修改：

```bash
copy configs\config.example.yaml configs\config.yaml
```

本地私有覆盖写入 `configs/local.yaml` 或 `configs/private.yaml`。这些文件应通过 `.gitignore` 隔离。

## 配置分区

| 分区 | 作用 |
|---|---|
| `app` | 项目名、运行环境和当前 profile |
| `input` | 输入来源能力和单文件读取上限 |
| `llm` | LLM 总开关、语义路由开关、模型、base url 和环境变量名 |
| `runtime` | 运行记录、幂等和 required 节点失败策略 |
| `workspace` | PRD 根目录、运行记录目录、产物目录、评审目录和元数据文件名 |
| `entries` | CLI、API、Chat、Bot 等协作入口开关 |
| `logging` | 日志目录、日志级别和密钥脱敏策略 |
| `workflow` | 工作流文件选择、人工 checkpoint 和生成节点 LLM 开关 |
| `rag` | RAG 索引、Embedding、检索数量和知识库路径 |
| `output` | 输出格式、候选产物写入和 Review Gate 要求 |
| `profiles` | 为后续多环境或多运行模式预留的 profile 覆盖 |

## 工作流配置

### 生成类 LLM 开关

`llm.enabled` 是全局 LLM 开关：

```yaml
llm:
  enabled: true
  semantic_router_enabled: true
```

- `enabled: false`：语义路由和生成节点都走确定性降级，不调用 `DEEPSEEK_API_KEY`。
- `semantic_router_enabled: false`：只关闭 LLM 语义路由，改用确定性路由。

LLM 连接参数可以写在 YAML 中，但密钥本身不能写入 YAML：

```yaml
llm:
  provider: deepseek
  api_key_env: DEEPSEEK_API_KEY
  base_url_env: DEEPSEEK_BASE_URL
  model_env: DEEPSEEK_MODEL
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
  enable_chat_fallback: true
  max_input_chars: 32000
```

优先级为：环境变量 > YAML。比如设置了 `DEEPSEEK_MODEL` 时，会覆盖
`llm.model`；设置了 `DEEPSEEK_BASE_URL` 时，会覆盖 `llm.base_url`。

需求分析、用例生成和 MVP 联合流程可单独控制：

```yaml
workflow:
  use_llm:
    requirement_analysis: true
    testcase_generation: true
    mvp_analysis_testcases: true
```

- `requirement_analysis: false`：需求分析生成不用 LLM。
- `testcase_generation: false`：测试用例生成不用 LLM。
- `mvp_analysis_testcases: false`：需求分析 + 测试用例联合流程不用 LLM。

`llm.enabled=false` 优先级更高；即使 `workflow.use_llm.*=true`，也不会调用 LLM。

## Runtime 和工作区配置

```yaml
runtime:
  record_runs: true
  idempotency_enabled: true
  fail_fast_required_nodes: true
  checkpointer: postgres
  checkpoint_postgres_dsn_env: AGENTIC_QA_CHECKPOINT_POSTGRES_DSN
  checkpoint_postgres_setup: true

workspace:
  prd_root: prd
  runtime_root: .runtime
  runs_dir_name: runs
  artifacts_dir_name: artifacts
  reviews_dir_name: reviews
  metadata_file: metadata.yml
```

- `record_runs`：是否写入运行记录。
- `idempotency_enabled`：是否启用幂等策略预留开关。
- `fail_fast_required_nodes`：required 节点失败时是否阻断流程。
- `checkpointer`：LangGraph checkpointer 存储，默认 `postgres`。
- `checkpoint_postgres_dsn_env`：PostgreSQL 连接串环境变量名，不要把真实密码写入 YAML。
- `checkpoint_postgres_setup`：是否在启动 checkpointer 时执行 `.setup()` 创建/迁移表。
- `workspace.*`：统一约束 PRD 工作区和运行记录的目录命名。

本地 PostgreSQL 示例：

```yaml
# configs/local.yaml 或 configs/private.yaml
runtime:
  checkpointer: postgres
  checkpoint_postgres_dsn_env: AGENTIC_QA_CHECKPOINT_POSTGRES_DSN
  checkpoint_postgres_setup: true
```

```powershell
$env:AGENTIC_QA_CHECKPOINT_POSTGRES_DSN="postgresql://postgres:<password>@localhost:5432/postgres?sslmode=disable"
```

## 协作入口和输出策略

```yaml
entries:
  cli_enabled: true
  api_enabled: false
  chat_enabled: true
  bot_enabled: false

output:
  write_artifact_preview: true
  require_review_gate: true
```

- `entries` 当前主要作为目标态入口能力声明，后续 API/Bot/Web 入口会读取这里。
- `write_artifact_preview`：生成结果先进入候选产物。
- `require_review_gate`：候选产物进入正式产物前必须经过 Review Gate。

### Workflow 文件选择

`workflow.intent_workflow_files` 可以覆盖某个 intent 需要加载的 workflow 文件：

```yaml
workflow:
  intent_workflow_files:
    testcase_generation:
      - workflows/10-runtime-testcase-generation-workflow.md
      - workflows/02-testcase-generation-workflow.md
```

`workflow.mvp_analysis_workflow_files` 和 `workflow.mvp_testcase_workflow_files` 用于当前 MVP Graph。

## RAG 密钥策略

RAG 密钥不写入 YAML。配置层只声明是否允许复用 LLM 密钥：

```yaml
rag:
  enabled: true
  embedding_provider: auto
  use_llm_api_key: true
  api_key_env: RAG_API_KEY
```

- `use_llm_api_key: true`：优先使用 `RAG_API_KEY`；未设置时允许复用 `DEEPSEEK_API_KEY`。
- `use_llm_api_key: false`：只允许使用 `RAG_API_KEY`；`auto` 无 key 时降级到本地 Embedding。
- `embedding_provider: openai`：强制外部 Embedding；没有可用 key 会失败。
- `embedding_provider: local`：强制本地哈希 Embedding，不调用外部 API。

## RAG 索引和审计

RAG 索引目录由 `rag.index_dir` 控制，默认是 `.rag_index/`。索引目录会写入
`manifest.json`，记录内容哈希、Embedding provider/model/dim、向量库、chunk 参数和知识库路径。
当这些元信息不一致时，Runtime 会自动重建索引，避免模型或维度变更后复用旧索引。

每次 Runtime run 会在 `.runtime/runs/<run_id>/rag.json` 写入 RAG 召回记录，包含实际 query、
截断后的 query_text、索引元信息、召回文档来源、heading、score 和 text_preview。

## RAG 调试命令

```bash
agentic-qa rag status
agentic-qa rag build
agentic-qa rag search "边界值 活动玩法"
```

- `status`：查看当前 RAG 配置、索引就绪状态和索引 manifest。
- `build`：按当前配置强制重建索引。
- `search`：按当前配置执行一次检索，并输出可审计的召回来源。
