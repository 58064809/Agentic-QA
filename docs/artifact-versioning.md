# 工作区与产物版本

```text
workspaces/<workspace_id>/
├── workspace.yml
├── sources/
├── runs/<run_id>/
│   ├── task.json
│   ├── plan.json
│   ├── state.json
│   ├── events.jsonl
│   └── tool-calls/
├── candidates/<run_id>/
├── reviews/<run_id>/
└── published/<artifact>/
    ├── current.*
    └── history/
```

所有读取、恢复和审核都以 `workspace_id + run_id` 精确定位，不进行全局 run ID 扫描。
候选创建后不可覆盖；需要修订时创建新 run。promote 将已批准候选复制到以 run ID 命名的历史
版本，并通过原子替换更新 `current.*`。批量发布会预校验并在失败时回滚，相同 run 重试不会
重复写入历史索引。

Workspace Repository 管理配置和 sources，Run/Event Repository 管理运行投影、事件与工具记录，
Artifact/Review Repository 管理候选、审核和发布。`state.json` 便于查询，PostgreSQL 中同一
workspace/run thread 的 checkpoint 是恢复事实来源。

带 idempotency key 的完成记录先原子写入 `tool-calls/`；模型崩溃后重试会复用记录，不重复执行
API/UI 等外部动作。旧 `prd/` 数据保持原样，但 v2 不读取、不迁移也不改写。
