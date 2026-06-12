# RAG

`rag/` 提供 Agentic-QA 的检索增强上下文能力，用于在 Runtime 生成需求分析、测试用例等草稿前，从 `knowledge/`、规则和模板文档中召回相关参考内容。

## 模块结构

| 模块 | 职责 |
|---|---|
| `config.py` | 读取和校验 RAG 环境变量或配置字典 |
| `loaders/` | 扫描目录或单个 Markdown 文件，加载知识库文本 |
| `splitter/` | 按 Markdown 标题、段落和固定窗口切分 Chunk |
| `embedding/` | OpenAI-compatible Embedding 与本地哈希 Embedding |
| `vector_store/` | FAISS 向量库与 NumPy 内存向量库 |
| `retriever/` | TopK 召回结果结构和 Prompt 上下文组装 |
| `manager.py` | 编排加载、切分、向量化、索引、检索和持久化 |

## 推荐配置

本地开发可先使用确定性哈希 Embedding，不需要 API Key：

```bash
RAG_ENABLED=true
RAG_EMBEDDING_PROVIDER=local
RAG_EMBEDDING_DIM=384
RAG_VECTOR_STORE=memory
RAG_INDEX_DIR=.rag_index
RAG_KNOWLEDGE_PATHS=knowledge/qa-methodology,knowledge/project-rules,knowledge/templates
```

接入真实 Embedding 服务时使用 OpenAI-compatible provider：

```bash
RAG_ENABLED=true
RAG_EMBEDDING_PROVIDER=openai
RAG_USE_LLM_API_KEY=true
RAG_EMBEDDING_MODEL=text-embedding-3-small
RAG_EMBEDDING_DIM=1536
RAG_VECTOR_STORE=faiss
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

`RAG_EMBEDDING_PROVIDER=auto` 会在检测到可用 RAG key 时使用 OpenAI-compatible Embedding，否则降级到本地哈希 Embedding。RAG key 的解析顺序为：

1. `RAG_API_KEY`
2. 当 `RAG_USE_LLM_API_KEY=true` 时复用 `DEEPSEEK_API_KEY`

如果希望 RAG 不复用 LLM 密钥，设置：

```bash
RAG_USE_LLM_API_KEY=false
```

## 使用示例

```python
from pathlib import Path

from rag import RagConfig, RagManager

config = RagConfig.from_env()
manager = RagManager(Path.cwd(), config)

manager.build_index()
context = manager.build_rag_context("登录需求应该覆盖哪些测试设计方法？")
```

## 持久化

索引默认写入 `.rag_index/`，该目录不应进入 Git。

- FAISS: `index.faiss` + `metadata.json`
- Memory: `memory_index.json`
- 内容哈希: `content_hash.txt`
- 索引元信息: `manifest.json`

当知识库内容、Embedding provider/model/dim、向量库、chunk 参数或知识库路径未变化时，
`RagManager.build_index()` 会复用已有索引；任一索引元信息不一致时会自动重建，避免改模型或维度后复用旧索引。

## 运行审计

Runtime 每次 run 会写入 `.runtime/runs/<run_id>/rag.json`。该文件记录：

- 实际用于检索的 query 和 query_text
- 使用的索引 manifest
- 召回文档的 source、heading、score、chunk_index 和 text_preview
- RAG 失败时的 error

该文件用于排查“本次生成到底参考了哪些知识库内容”。

## CLI 调试

```bash
agentic-qa rag status
agentic-qa rag build
agentic-qa rag search "边界值 活动玩法"
```

- `status` 查看当前 RAG 配置和索引状态。
- `build` 按当前配置强制重建索引。
- `search` 执行一次检索并输出召回来源。

## Query 构造

Runtime 不再直接把整篇 PRD 截断后送入 Embedding。生成节点会先抽取用户输入、Markdown 标题、
业务规则、边界、状态、流程、异常、风险、字段、接口、权限、奖励、邀请、分享、测试和用例相关行，
再构造检索 query。这样能降低长 PRD 噪声，并让召回更贴近测试设计需要。

## 降级策略

- `RAG_ENABLED=false` 时不召回上下文。
- 未安装 FAISS 时，`RAG_VECTOR_STORE=faiss` 会自动降级到内存向量库。
- `RAG_EMBEDDING_PROVIDER=auto` 且没有可用 RAG key 时，会使用本地哈希 Embedding。
- `RAG_EMBEDDING_PROVIDER=openai` 且没有可用 RAG key 时，会失败并提示配置密钥。
- 检索失败时 Runtime 会追加 warning，并继续走无 RAG 上下文流程。
