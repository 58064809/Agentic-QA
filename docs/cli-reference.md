# CLI 参考

## 调用形式

```powershell
python -m harness [--repo-root <path>] <group> <command> ...
```

`--repo-root` 必须位于子命令之前；默认值为当前目录。

## 命令

| 命令 | 必需参数 | 主要选项 | 输出/副作用 |
|---|---|---|---|
| `workspace create` | `workspace_id` | 重复 `--quality-policy` | 创建 v2 workspace |
| `run start` | `workspace_id goal` | artifact、ExecutionProfile | 创建 run、冻结来源并执行到 Review Gate |
| `run get` | `workspace_id run_id` | 无 | 只读返回 RunSnapshot |
| `run resume` | `workspace_id run_id` | 无 | 仅恢复崩溃执行 |
| `run review` | `workspace_id run_id decision` | artifact、variant、审核信息 | 写审核记录；approve 可触发发布 |
| `run diff` | `workspace_id run_id artifact` | before、after | 只读返回 unified diff |
| `eval run` | 无 | 无 | 运行离线确定性评估 |
| `request run` | `request_file` | 重复 `--allow-source-root` | 导入本地来源并幂等执行到 Review Gate |
| `request schema` | 无 | 无 | 输出 AgentRequest v1 JSON Schema |
| `mcp serve` | 无 | 重复 `--allow-source-root` | 启动本地 stdio MCP Server |

## `request` 与 `mcp`

`request run` 只接受 `.json`、`.yaml` 或 `.yml`，并要求至少一个绝对
`--allow-source-root`。请求固定为 `analysis-only`，不会调用人工 Review 或发布。

```powershell
python -m harness request run .\request.yml `
  --allow-source-root D:\Requirements

python -m harness mcp serve `
  --allow-source-root D:\Requirements
```

MCP 工具、请求字段和安全限制见[跨 AI 接入](agent-integration.md)。

## `run start`

| 参数 | 默认值 | 规则 |
|---|---|---|
| `--artifact` | `testcases` | 可重复；必须是受支持 artifact |
| `--environment` | `analysis-only` | 禁止 production-like 名称 |
| `--base-url-env` | 空 | 非 analysis-only 时必须匹配 workspace policy |
| `--allow-http-method` | `GET, HEAD, OPTIONS` | 可重复且只能收窄 workspace policy |
| `--allow-ui-mutations` | false | analysis-only 禁止；workspace 必须先授权 |
| `--request-timeout-seconds` | `10` | 1–60 秒且不得超过 workspace policy |

Artifact：`requirement_analysis`、`testcases`、`api_test_draft`、`ui_test_draft`、
`api_discovery_report`、`qa_report`、`execution_report`、`failure_analysis`、`bug_draft`。

## `run review`

| decision | 是否需要 version | 是否发布 | 状态结果 |
|---|---:|---:|---|
| `approve` | 是，每个目标恰好一个 | 质量门与 Repository 复验通过后发布 | `published` 或保留其他 artifact 状态 |
| `hold` | 否 | 否 | `on_hold` |
| `reject` | 否 | 否 | `rejected` |
| `revise` | 否；必须有 `--revision-request` | 否 | `needs_revision` |

通用参数：

| 参数 | 规则 |
|---|---|
| `--artifact` | 单个 artifact 或 `all`；多 Candidate 时必须指定 |
| `--variant` | approve 专用，可重复，格式 `artifact=raw|normalized` |
| `--reason` | 必填的人工决定原因 |
| `--reviewed-by` | 必填的审核人标识 |
| `--revision-request` | revise 必填 |

存在 normalized 时 CLI 不替审核人选择，必须显式提供 variant。

## `run diff`

`--before` 和 `--after` 均为必填，端点只能是 `raw`、`normalized` 或 `published`。端点必须真实
存在；remediation patch 不是可比较或可发布的 ArtifactVariant。

## 状态与下一步

| Run 状态 | 用户动作 |
|---|---|
| `planning`、`running`、`recoverable` | 进程中断后可 `run resume` |
| `needs_human_review` | 检查 Candidate 后 `run review` |
| `on_hold` | 等待确认，之后继续 `run review` |
| `partial` | 可查询和审核，但不能 approve/promote |
| `needs_revision`、`rejected` | 更新输入后创建新 run |
| `published` | 从 `published/<artifact>/current.*` 读取 |
| `failed` | 查看 snapshot errors 和 events；不能伪装成 Review |

## 退出码

| 退出码 | 含义 |
|---:|---|
| `0` | 命令成功；`eval run` 的评估通过 |
| `1` | `eval run` 完成但评估未通过 |
| `2` | 参数、配置或运行错误；原因写入 stderr |
