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
│   ├── discovery-catalog.json     # API Discovery 的脱敏机器目录
│   ├── requirement-catalog.json   # requirement_analysis 的强类型附件
│   ├── requirement-delta.json     # requirement_delta 的强类型附件
│   ├── impact-analysis.json       # impact_analysis 的强类型附件
│   ├── risk-catalog.json          # testcases 的 RiskCatalog v2
│   ├── test-design-plan.json      # 方法适用性与组合预算
│   ├── test-case-set.json         # TestCaseSet v2
│   ├── retrieval-provenance.json  # retrieval ID/chunk 引用
│   └── manifest.json
├── reviews/<run_id>/
├── published/<artifact>/
    ├── current.*
    └── history/
├── allure-history.jsonl
└── executions/<execution-id>/
    ├── manifest.json
    ├── execution-plan.json         # 请求前 create-only 的脱敏执行快照
    ├── evidence.json
    ├── execution-events.jsonl
    ├── report-summary.json
    ├── cleanup-summary.json
    ├── .cleanup-journal.enc       # 仅在需要 cleanup 时存在
    ├── allure-results/
    ├── allure-report/             # 本地 Allure CLI 可用时存在
    └── triage/collections/<collection-id>/
        ├── collection-manifest.json
        ├── log-evidence.json
        ├── log-analysis.json
        ├── trace-evidence.json       # source 包含 traces 且产生审计结果时存在
        ├── trace-analysis.json       # Trace Evidence 存在时产生
        ├── root-cause-graph.json
        ├── failure-triage.json
        └── bug-draft.json         # Bug Gate 通过时存在
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
| Knowledge publication outbox | published 到持久知识的派生索引状态 | 幂等 pending/completed/failed | `knowledge status/index-run`；不改变 published truth |
| API execution manifest | 防重放状态与产物索引投影 | 原子替换 | 执行、测试、cleanup、报告四状态 |
| API Execution Evidence | 用例与断言审计事实 | create-only | 试跑结论；v2 为新执行，v1 只读投影 |
| API execution events | 脱敏、追加式 SHA-256 哈希链 | append-only | 请求边界与崩溃定位 |
| execution plan | published 与执行策略的脱敏冻结快照 | create-only | 请求前冻结；cleanup resume 和历史报告从这里解析原发布版本 |
| cleanup journal | AES-256-GCM 加密的 armed/pending/running 状态 | 原子替换 | armed 供人工核对；仅恢复从未发送的 pending cleanup |
| Allure results/history/report | Evidence 的展示投影 | 可重新生成 | 状态浏览、趋势与回归 |
| Failure collection 产物 | 脱敏日志/调用链、确定性分析与证据图、引用式分诊和可选 Bug Draft | staging 后原子提交；collection 内 create-only | 显式失败分诊；不修改原 execution |

历史 Allure 重建以 execution 目录中的 immutable Execution Plan 为入口，再精确解析 published
history；workspace 当前服务绑定、current YAML、认证和安全策略不参与历史结果解释。Plan、manifest、
Evidence 或 history 的身份与哈希不一致时，报告预检直接失败，不回退到当前发布。

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
| `discovery-catalog.json` | API Discovery 是 | 与审核版本一起进行 hash 选择，批准后发布为 `current.catalog.json` |

发布选择与拒绝条件见 [Review Gate](review-gate.md)。
