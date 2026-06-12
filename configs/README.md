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
