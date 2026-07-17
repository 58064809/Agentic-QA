# 工作区与产物版本

```text
workspaces/<id>/
├── workspace.yml
├── sources/
├── runs/<run_id>/
│   ├── task.json
│   ├── plan.json
│   ├── state.json
│   ├── events.jsonl
│   ├── checkpoints/graph.sqlite
│   └── tool-calls/
├── candidates/<run_id>/
├── reviews/<run_id>/
├── published/<artifact>/
│   ├── current.*
│   └── history/index.yml
└── memory/
```

候选创建后不得覆盖。promote 将候选复制到以 run_id 命名的 history，并以原子替换更新
`current.*`。批量发布先预校验并在失败时回滚；相同 run 重试不会重复添加历史索引。
`state.json` 是公开投影，`graph.sqlite` 才是执行恢复事实来源。旧 `prd/` 不参与解析。
