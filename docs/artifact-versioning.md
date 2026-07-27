# 工作区与产物版本

本页适合排查 Candidate、审核记录、发布历史或恢复问题，目录图展示每类文件由哪个阶段产生。

## 目录

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
│   ├── remediation.patch          # 可选，仅用于修订建议
│   ├── quality-report.json
│   ├── generation-report.json     # 可选；模型调用与质量修订审计
│   └── manifest.json
├── reviews/<run_id>/
└── published/<artifact>/
    ├── current.*
    └── history/
```

## 事实与可变性

| 数据 | 职责 | 可变性 | 恢复用途 |
|---|---|---|---|
| PostgreSQL checkpoint | LangGraph 执行状态 | 追加/更新 | 崩溃恢复事实来源 |
| `state.json` | Run 查询投影 | 原子替换 | 查询，不替代 checkpoint |
| Source Bundle/snapshot | 本 run 实际来源 | create-only | RAG、Agent、Tool、质量复用 |
| Candidate Manifest | Candidate 文件集合与 provenance | create-only | 审核/发布事实来源 |
| quality report | variant verdict 与评估审计 | create-only | Review 与 promote |
| generation report | 是否使用 LLM、模型路由、Token 与修订次数 | create-only | 生成过程审计 |
| Review Record | 人工决定与批准版本 | 按 artifact 原子写 | 审计 |
| published history | 已发布只增不改版本 | create-only | 历史追踪 |
| published current | 当前版本指针内容 | 原子替换 | 使用者读取 |

## 原子边界

| Bundle | 协议 |
|---|---|
| Source | run 级文件锁；staging 写快照；最后提交 manifest；失败清理未提交快照 |
| Candidate | artifact 锁；同父 staging；逐文件 fsync；manifest 最后写；同卷 rename |
| Publication | run 级锁与 Journal；幂等 history/current/Review/Snapshot/event；完成后 committed |

读取方只接受有效 manifest 的 final bundle，不读取 staging。Candidate 已存在时，仅当 assessment key
与全部 hashes 相同才复用，否则拒绝覆盖。

## 版本语义

| 文件 | 可发布 | 规则 |
|---|---:|---|
| `raw.*` | 是 | Agent 原始输出；质量策略只读评估并保留原文件 |
| `normalized.*` | 是 | 可选，仅允许业务语义不变的机械格式调整 |
| `normalization.patch` | 否 | 审计表示层变化 |
| `remediation.patch` | 否 | 修订建议；接受建议后由新 run 形成新的 raw |
| `generation-report.json` | 否 | 记录 `llm_used`、每次模型调用结果和质量回灌次数 |

发布选择与拒绝条件见 [Review Gate](review-gate.md)。
