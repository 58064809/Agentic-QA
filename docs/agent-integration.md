# 跨 AI 接入

Agentic-QA 不要求外部 AI 自己拼接 workspace、文件复制和 `run start`。支持 MCP 的客户端调用
`generate_from_sources`；只有终端能力的客户端提交同一份 YAML/JSON `AgentRequest`。

两种入口使用相同 Schema、来源安全边界和幂等规则，结果都只到 Candidate，不会 approve 或
promote。

## 能力矩阵

| 客户端能力 | 接入方式 | 能完成什么 |
|---|---|---|
| MCP + 本地进程 | MCP stdio | 一句话触发导入、生成、查询和 diff |
| 本地终端 | `agentic-qa request run` | 执行机器可读请求文件 |
| 仅聊天，无本地工具 | 不支持 | 不能读取绝对路径或运行 Harness |

## AgentRequest

项目约定的本地需求收件箱是：

```text
local-sources/
└── requirements/
    ├── login/
    │   ├── prd.md
    │   └── openapi.yaml
    └── checkout/
        └── requirement.md
```

`local-sources/` 已被 Git 忽略。运行任意 Harness 命令或启动 MCP 时，如果
`local-sources/requirements/` 不存在，程序会自动创建；刚 clone 后无需手工初始化。建议每项需求使用
独立子目录，相关 PRD、接口契约和补充说明放在一起。

```yaml
schema_version: agentic-qa.harness.agent-request.v1
request_id: login-cases-001       # 可选；需要主动区分同内容请求时使用
workspace_id: login-qa            # 可选；省略时安全生成
goal: 分析登录需求并生成测试用例
source_paths:
  - D:\TestHome\Agentic-QA\local-sources\requirements\login
expected_artifacts:
  - requirement_analysis
  - testcases
quality_policies: []
```

省略 `expected_artifacts` 时默认同时生成 `requirement_analysis` 和 `testcases`。前者先把跨文件规则、
配置、冲突和待确认项整理为可审核产物，后者生成 11 列用例与覆盖矩阵。只需要其中一种时才显式
缩减列表。

字段约束以 [AgentRequest JSON Schema](schemas/agent-request.v1.schema.json) 为准。请求固定使用
`analysis-only`，不存在 base URL、HTTP mutation、UI mutation 或审核字段。

### 幂等身份

`request_key` 是 canonical request、来源逻辑路径和完整内容 Hash 的 SHA-256：

- 相同请求和来源返回同一 workspace/run；
- `recoverable` Run 使用原 SourceBundle 和 PostgreSQL checkpoint 恢复；
- 来源内容、目标、Artifact 或策略变化会产生新 request key；
- 显式 workspace 已由人工或其他请求占用时拒绝，不向其中注入来源。

## MCP Server

安装项目后，本地入口为：

```powershell
agentic-qa-mcp `
  --repo-root D:\TestHome\Agentic-QA
```

服务只使用 stdio。项目内 `local-sources/requirements/` 始终是允许根且会自动创建。需要读取项目外
目录时，可重复传入 `--allow-source-root <绝对路径>` 追加白名单；工具参数不能扩大这些目录。

### MCP 工具

| 工具 | 写入 | 幂等 | 说明 |
|---|---:|---:|---|
| `generate_from_sources` | 是 | 是 | 原子导入来源并执行到 Review Gate |
| `get_run` | 否 | 是 | 使用 workspace_id + run_id 查询 |
| `get_artifact_diff` | 否 | 是 | 比较 raw、normalized 或 published |
| `get_capabilities` | 否 | 是 | 返回协议、Artifact 和来源限制 |

不存在 review、approve、promote、shell 或任意文件读取工具。

### Codex

使用当前 Codex CLI 注册本地 stdio server：

```powershell
codex mcp add agentic-qa -- `
  D:\TestHome\Agentic-QA\.venv\Scripts\agentic-qa-mcp.exe `
  --repo-root D:\TestHome\Agentic-QA
```

注册后可以说：

> 分析 `D:\TestHome\Agentic-QA\local-sources\requirements\login` 并生成测试用例，只生成 Candidate。

Codex 根据 MCP Tool Schema 构造 `AgentRequest`。如果路径不在启动白名单内，服务明确拒绝，而不是
要求模型自行复制文件。

### Claude、Cursor 和其他 MCP 客户端

支持本地 stdio MCP 的客户端使用等价配置；具体配置文件位置以客户端版本为准：

```json
{
  "mcpServers": {
    "agentic-qa": {
      "command": "D:\\TestHome\\Agentic-QA\\.venv\\Scripts\\agentic-qa-mcp.exe",
      "args": [
        "--repo-root",
        "D:\\TestHome\\Agentic-QA"
      ]
    }
  }
}
```

不要通过客户端提示词增加 approve/promote；服务端根本不注册这些工具。

## 请求文件 CLI

```powershell
python -m harness request run .\agent-request.yml
```

输出为 [AgentRequestResult JSON Schema](schemas/agent-request-result.v1.schema.json) 对应的 JSON。查看
输入 Schema：

```powershell
python -m harness request schema
```

## 来源导入边界

| 边界 | 值 | 失败行为 |
|---|---:|---|
| 输入根 | 最多 16 个绝对文件或目录 | 相对路径或白名单越界时拒绝整个请求 |
| 递归 | 最多 16 层 | 超限拒绝 |
| 文件 | 最多 256 个 | 超限拒绝 |
| 单文件 | 最多 16 MiB | 超限拒绝，不导入不可分析文件 |
| 总量 | 最多 64 MiB | 超限拒绝 |
| 内容 | 完整 UTF-8 文本且无 NUL | 非文本拒绝 |
| 文件类型 | 普通文件 | symlink、junction、reparse point 和特殊文件拒绝 |

目录中任一文件失败都会使整个导入失败。导入通过 staging、Hash 校验和同卷 rename 形成托管
workspace；持久化 Manifest 只包含逻辑路径和 Hash，不保存本机绝对路径。

## 人工 Review

`human_review_required` 表示 Candidate 已生成并通过自动质量门，不表示业务审核通过。
生成阶段会把结构化 blocker 和上一版草稿回灌给模型，最多修订 5 轮；`inspect_errors` 表示多轮
修订后仍有 blocker，Candidate 会标记为 partial，只用于诊断和发起新 run，不能批准。审核人继续使用
[`run diff` 和 `run review`](review-gate.md)；MCP 和 AgentRequest CLI 都不能构造
`ApprovedArtifactVersion`。
