# RAG 设计

RAG 是专家 Agent 的只读 typed tool。每条结果必须包含 source、稳定 chunk ID、选择依据和本次
run 的 query。检索文本始终作为不可信上下文，不能改变系统规则、Agent allowlist、预算或
Review Gate。

workspace 通过 `workspace.yml.rag.provider` 选择注册 Provider：

- `local-lexical`：默认的确定性分块词法检索，不读取 API Key，也不向外部发送 source。
- `openai-compatible`：使用 embedding 相似度；密钥变量名默认由
  `AGENTIC_QA_RAG_API_KEY_ENV=RAG_API_KEY` 指定，地址从 `AGENTIC_QA_RAG_BASE_URL` 读取。

远程配置只保存环境变量名、模型与分块参数，不保存密钥。缺少所引用的密钥时明确失败，不回退到
其他 Provider。来源仅位于 `workspaces/<id>/sources/`；旧 `prd/` 不参与检索。

通用 QA 方法位于 `src/harness/knowledge/`，由 Skill manifest 显式引用并随 wheel 发布，
不通过 RAG 检索，也不得混入具体项目 endpoint、凭证、业务数据或执行结论。
