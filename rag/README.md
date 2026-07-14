# RAG Runtime

RAG 的设计契约统一见 `docs/rag-design.md`，运行记录契约见 `docs/rag-run-record-spec.md`。

当前实现由 `rag/manager.py` 编排 loader、splitter、embedding、vector store、retriever 和 context builder。默认可使用本地哈希 Embedding；配置远程 provider 时从环境变量读取密钥，密钥不得进入索引、trace 或产物。

调试入口：

```bash
python -m runtime.cli rag status
python -m runtime.cli rag build
python -m runtime.cli rag search "query"
```
