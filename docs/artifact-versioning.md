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
│   ├── checkpoints/
│   └── tool-calls/
├── candidates/<run_id>/
├── reviews/<run_id>/
├── published/<artifact>/
│   ├── current.*
│   └── history/index.yml
└── memory/
```

候选创建后不得覆盖。promote 将候选复制到以 run_id 命名的 history，并以原子替换更新
`current.*`。相同 run 重试不会重复添加历史索引。旧 `prd/` 与 `.runtime` 不参与解析。
