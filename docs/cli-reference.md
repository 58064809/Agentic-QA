# CLI 参考

本页用于查询命令位置、参数默认值、系统响应和退出码；完整操作示例见[从零开始](getting-started.md)。

## 调用形式

```powershell
python -m harness [--repo-root PATH] <command>
```

`--repo-root` 是顶层参数，解析位置在子命令之前；省略时使用当前目录。

## 命令

| 命令 | 必需参数 | 主要作用 |
|---|---|---|
| `workspace create` | `workspace_id` | 创建 v2 workspace；可重复指定 `--quality-policy` |
| `run start` | `workspace_id goal` | 冻结来源并执行到 Review Gate |
| `run get` | `workspace_id run_id` | 只读返回 RunSnapshot |
| `run resume` | `workspace_id run_id` | 恢复 recoverable run |
| `run review` | `workspace_id run_id decision` | 写人工 Review；approve 可触发发布 |
| `run diff` | `workspace_id run_id artifact` | 比较 raw、normalized 或 published |
| `eval run` | 无 | 运行离线工作流 Eval 和五类脱敏 Golden Eval |
| `eval live` | 无 | 使用显式配置的模型密钥生成 nightly Candidate，不发布 |
| `request run` | `request_file` | 导入允许根内的来源并幂等执行到 Review Gate |
| `request schema` | 无 | 输出 AgentRequest v1 JSON Schema |
| `mcp serve` | 无 | 启动受限的 stdio MCP Server |

## `run start`

| 参数 | 默认值 | 系统行为 |
|---|---|---|
| `--artifact` | `testcases` | 可重复；未知 artifact 返回参数错误 |
| `--environment` | `analysis-only` | production-like 名称被安全校验拒绝 |
| `--base-url-env` | 空 | 非 analysis-only 时与 workspace policy 比对 |
| `--allow-http-method` | `GET, HEAD, OPTIONS` | 超出 workspace policy 的方法被拒绝 |
| `--allow-ui-mutations` | false | workspace 未授权时返回权限错误 |
| `--request-timeout-seconds` | `10` | 接受 1–60 秒，并与 workspace policy 上限比对 |

Artifact：`requirement_analysis`、`testcases`、`api_test_draft`、`ui_test_draft`、
`api_discovery_report`、`qa_report`、`execution_report`、`failure_analysis`、`bug_draft`。

## `run review`

| decision | version | 发布 | 结果 |
|---|---:|---:|---|
| `approve` | 每个目标恰好一个 | 复验通过后发布 | `published` 或其余 artifact 状态 |
| `hold` | 不需要 | 否 | `on_hold` |
| `reject` | 不需要 | 否 | `rejected` |
| `revise` | 不接收版本；缺少 `--revision-request` 时返回参数错误 | 否 | `needs_revision` |

多 Candidate 时，`--artifact` 接受单个 artifact 或 `all`；缺少目标会返回歧义错误。approve 通过
可重复的 `--variant artifact=raw|normalized` 明确选择版本，CLI 不代替审核人决定。

## `run diff`

`--before` 与 `--after` 接受 `raw`、`normalized` 或 `published`。remediation patch 不属于
ArtifactVariant，因此不会出现在差异端点或发布版本中。

## `request` 与 `mcp`

`request run` 接受 JSON/YAML。`local-sources/requirements/` 是默认允许根；额外根使用可重复的
`--allow-source-root`。AgentRequest 固定为 analysis-only，不暴露 Review、approve、promote、shell
或任意文件读取工具。

## Eval

`eval run` 不需要模型密钥，包含：

- recorded workflow、MCP snapshot、Review Gate 和 deterministic promote；
- login-lock、order-refund、coupon-boundary、settlement-rounding、
  city-opening-rewards 五类脱敏 Golden Case。每个 Case 分别读取
  `expectations.json`、`baseline-testcases.json`、
  `candidate-requirement-catalog.json` 和 `candidate-testcases.md`；候选缺失时失败，
  并报告 `baseline_score` 与 `baseline_gap`，不会把人工基线当成待测产物；
- 规则召回、覆盖率、幻觉率、重复率、边界/状态覆盖和可执行性评分。

`eval live` 需要显式模型配置。默认场景是脱敏的 `login-lock`；环境变量
`AGENTIC_QA_LIVE_EVAL_CASE=lottery-assistance` 会切换到规则更密集的助力抽奖场景。系统生成真实
隔离 Candidate，停在 Review Gate 后读取本次 `requirement_analysis/raw.md` 与
`testcases/raw.md` 计算规则召回、覆盖、幻觉、重复、边界/状态和可执行性分数；状态正确但质量分
不足仍返回失败。设置
`AGENTIC_QA_LIVE_EVAL_OUTPUT` 时，只导出脱敏 `source-bundle.json`、两类 raw artifact、
`quality-report.json` 与 `generation-report.json` 供人工审查，不导出整个 workspace。

## 退出码

| 退出码 | 含义 |
|---:|---|
| `0` | 命令成功；Eval 通过 |
| `1` | Eval 完成但未通过 |
| `2` | 参数、配置或运行错误 |
