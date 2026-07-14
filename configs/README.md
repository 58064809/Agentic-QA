# Configs

`configs/` 只保存可提交的非敏感运行参数。Workflow 文件、Prompt 清单和 Runtime context files 不允许通过配置覆盖。

## 加载顺序

`runtime.config.load_app_config()` 按顺序合并：

1. `configs/config.yaml`
2. `configs/local.yaml`
3. `configs/private.yaml`

后加载文件覆盖先加载文件。缺少 `configs/config.yaml` 时使用代码默认值。

复制示例：

```powershell
copy configs\config.example.yaml configs\config.yaml
```

本地私有覆盖写入 `configs/local.yaml` 或 `configs/private.yaml`，并由 `.gitignore` 隔离。

## 配置分区

| 分区 | 作用 |
|---|---|
| `app` | 项目名、环境和 profile |
| `input` | 输入能力与读取上限 |
| `llm` | LLM 总开关、语义路由和模型连接参数 |
| `runtime` | 运行记录、幂等、required 节点和 checkpointer |
| `workspace` | PRD、Runtime、runs、artifacts、reviews 与 metadata 名称 |
| `entries` | CLI、API、Chat、Bot 开关 |
| `logging` | 日志与脱敏 |
| `workflow` | 各生成任务是否调用 LLM |
| `rag` | Embedding、索引、检索和知识路径 |
| `output` | 输出格式、候选写入与 Review Gate |
| `observability` | LangSmith 配置 |
| `profiles` | 环境级覆盖 |

## Workflow 配置边界

Workflow ID、YAML 文件和 context files 由 `runtime/workflow/catalog.py` 唯一管理，配置层不能覆盖。

```yaml
workflow:
  use_llm:
    requirement_analysis: true
    testcase_generation: true
    mvp_analysis_testcases: true
    api_test_draft: true
    ui_test_draft: true
    api_discovery_report: true
    qa_report: true
```

`llm.enabled: false` 的优先级高于任务级开关。

禁止在配置中声明 Workflow Markdown、任意 context 文件列表或旧 MVP 文件覆盖项。

## LLM

```yaml
llm:
  enabled: true
  semantic_router_enabled: true
  provider: deepseek
  api_key_env: DEEPSEEK_API_KEY
  base_url_env: DEEPSEEK_BASE_URL
  model_env: DEEPSEEK_MODEL
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
  enable_chat_fallback: true
  max_input_chars: 32000
```

优先级：环境变量覆盖 YAML。密钥本身不得写入 YAML。

## Runtime 与工作区

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

PostgreSQL 连接串只从 `AGENTIC_QA_CHECKPOINT_POSTGRES_DSN` 读取。Session Store 使用独立环境变量 `AGENTIC_QA_STORE_POSTGRES_DSN`。

## 输出

```yaml
output:
  markdown: true
  yaml: true
  json: true
  write_artifact_preview: true
  require_review_gate: true
```

`write_artifact_preview` 表示先写 `runs/<run-id>/<artifact>.preview.md`；`artifact-preview.md` 只保存候选索引。

## RAG

```yaml
rag:
  enabled: true
  embedding_provider: auto
  use_llm_api_key: true
  api_key_env: RAG_API_KEY
  vector_store: faiss
  index_dir: .rag_index
```

- `auto`：按可用配置选择外部或本地 Embedding。
- `openai`：强制外部 Embedding，无 key 时失败。
- `local`：使用本地 Embedding，不调用外部 API。
- `use_llm_api_key: true`：未设置 `RAG_API_KEY` 时允许复用 LLM key。

索引 manifest 必须记录 provider、model、dim、chunk 参数、知识路径和内容哈希；不一致时重建。

## LangSmith

```yaml
observability:
  provider: langsmith
  enabled: true
  endpoint: https://api.smith.langchain.com
  api_key_env: LANGSMITH_API_KEY
  project: agentic-qa
```

API key 只从环境变量读取。Runtime 只传递 `workflow_id`、`run_id`、`thread_id`、tags 和非敏感 metadata。

## 校验

```bash
python scripts/validate_docs_consistency.py
pytest tests/unit/test_runtime_config.py
ruff check .
```
