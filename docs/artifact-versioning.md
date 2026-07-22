# 工作区与产物版本

```text
workspaces/<workspace_id>/
├── workspace.yml
├── sources/
├── runs/<run_id>/
│   ├── source-bundle.json
│   ├── source-snapshot/
│   ├── state.json
│   └── events.jsonl
├── candidates/<run_id>/<artifact>/
│   ├── raw.md
│   ├── normalized.md              # 可选
│   ├── normalization.patch        # 可选
│   ├── remediation.patch          # 可选、不可发布
│   ├── quality-report.json
│   └── manifest.json
├── reviews/<run_id>/
└── published/<artifact>/
    ├── current.*
    └── history/
```

所有查询、恢复和审核都使用 `workspace_id + run_id`，不全局扫描 run ID。raw 是 Agent 原始输出，
永不被策略或 Normalizer 覆盖。normalized 只能包含业务语义不变的表示层调整；remediation 是建议，
需要新 run 才能成为新的 raw artifact。

Candidate 采用同父目录 staging、逐文件 fsync、最后写 manifest、平台文件锁和同卷目录 rename。
读取方只识别带有效 manifest 的 final directory，因此不会看到半写 bundle。若 final 已存在，相同
assessment key 且全部 hashes 一致时复用；否则拒绝覆盖。

ArtifactCandidate 不保存 `quality_passed`。可发布性由质量报告针对具体 variant 派生。Promote 将
人工批准的强类型版本写入历史索引，并保存 variant、内容 hash 和 assessment key。旧 Candidate
可以查询，但缺少 provenance 时不能 approve/promote，也不会自动补算。

PostgreSQL checkpoint 是执行恢复事实来源；state.json 是查询投影；source snapshot 冻结本 run 的
实际输入；Candidate manifest 和 quality report 是审核与发布事实来源。这些职责不可互相替代。
