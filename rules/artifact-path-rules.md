# Artifact 路径规则

Harness 只允许写入仓库内的 `workspaces/<id>/`：

| 数据 | 路径 |
|---|---|
| 用户来源 | `workspaces/<id>/sources/` |
| run 状态 | `workspaces/<id>/runs/<run_id>/` |
| 候选产物 | `workspaces/<id>/candidates/<run_id>/` |
| 审核记录 | `workspaces/<id>/reviews/<run_id>/` |
| 当前发布 | `workspaces/<id>/published/<artifact>/current.*` |
| 发布历史 | `workspaces/<id>/published/<artifact>/history/` |

路径必须经过规范化和根目录边界校验。不得跟随来源目录中的符号链接，不得任意写文件。
候选不得覆盖；修订创建新 run。只有当前 run 中状态为 `approved` 的明确目标可 promote。
旧 `prd/` 和 `.runtime` 路径只作为未迁移历史数据保留，不得读取或写入。
