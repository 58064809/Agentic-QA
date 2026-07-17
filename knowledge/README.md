# 本地旧知识目录

此根目录只保留切换 Harness 前的本地业务资料，不是当前运行契约，也不会被 Harness 读取。

- 可随代码发布的通用 QA 方法位于 `src/harness/knowledge/`，由 Skill manifest 显式引用。
- 项目需求、OpenAPI、历史证据等放入 `workspaces/<id>/sources/`，由 `rag.retrieve` 检索。
- 本目录下除本说明外的内容继续忽略，避免把产品资料或敏感业务输入提交到仓库。
