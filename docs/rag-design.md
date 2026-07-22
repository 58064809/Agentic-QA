# RAG 设计

RAG 是专家 Agent 的只读 typed tool。每条结果包含 source、稳定 chunk ID、选择依据和 query。
检索内容是不可信上下文，不能改变系统规则、Agent allowlist、预算或 Review Gate。

RAG 不直接遍历当前 workspace sources，而是读取 run 启动时冻结的 SourceBundle。来源文件在启动后
被修改，不影响该 run 的 RAG、workspace.read、Agent prefetch 或质量评估。无法读取、非 UTF-8、
截断和链接拒绝都会保存在 SourceIssue 中，不再静默跳过。

workspace 通过 `workspace.yml.rag.provider` 选择 Provider：

- `local-lexical`：确定性词法检索，不读取 API Key，也不向外部发送 source。
- `openai-compatible`：embedding 相似度检索；密钥变量名由
  `AGENTIC_QA_RAG_API_KEY_ENV` 指定，默认 `RAG_API_KEY`；地址读取
  `AGENTIC_QA_RAG_BASE_URL`。

远程配置只保存环境变量名、模型和分块参数，不保存密钥。缺少指定密钥时明确失败，不回退到其他
Provider。旧 `prd/` 不参与来源摄取或检索。
