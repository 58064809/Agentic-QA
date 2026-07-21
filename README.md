# Agentic-QA

Agentic-QA 是面向项目内 QA 团队的“测试主管 Agent + 专家 Agent”协作 Harness。
调用方提交开放式测试目标，主管动态选择专家并并行派发无依赖任务。所有结果先进入候选区；
只有人工 ReviewDecision 为 `approve` 时，确定性 promote 才会写入 published。

LangGraph 只作为内部动态派发与恢复后端，不属于公开领域协议。公开 Python API 为：

```python
from harness import Harness, ReviewDecision, TaskRequest

harness = Harness(".")
snapshot = harness.run(
    TaskRequest(
        workspace="demo",
        goal="分析登录需求并设计测试",
        expected_artifacts=["requirement_analysis", "testcases"],
    )
)

# 人工审核后调用；Agent 无权构造或代替该决定。
snapshot = harness.resume(
    snapshot.run_id,
    ReviewDecision(
        intent="approve",
        target_artifact="all",
        reason="已完成人工审核",
        reviewed_by="qa_owner",
    ),
)
```

## 当前能力

- 真实 LangGraph StateGraph、SQLite checkpoint、动态 `Send` 并行派发与崩溃恢复。
- 测试主管结构化规划、依赖检查、专家验收与有限重规划。
- 需求、风险、测试设计、API、UI、执行、失败分诊、报告和审核辅助专家。
- 声明式 Agent、Skill、Tool manifest；Skill 显式加载随包发布的通用 QA 知识，每个专家只
  看到自己声明的知识和 allowlist 工具。
- `agentic-qa.harness.*.v1` 任务、计划、manifest、事件、快照和审核契约。
- 新 `workspaces/<id>/` 工作区、run checkpoint、候选、review 和发布历史。
- API cases v1.1、execution evidence v1、failure triage v1 领域 Schema。
- OpenAPI、轻量 RAG、API execution/evidence，以及 MCP 工具快照、校验和脱敏。
- 硬 Review Gate：Agent 只能准备摘要与 diff，不能 approve 或 promote。

## 主链路

```text
TaskRequest
  -> qa_supervisor 规划
  -> 专家 Agent 动态并行派发
  -> 证据与质量检查
  -> workspaces/<id>/candidates/<run_id>/
  -> needs_human_review（停止）
  -> 人工 ReviewDecision
  -> approved
  -> deterministic promote
  -> workspaces/<id>/published/<artifact>/current.*
```

## 快速开始

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

$env:DEEPSEEK_API_KEY="<your-key>"

agentic-qa workspace init demo
agentic-qa run demo "分析登录需求并生成测试用例"
agentic-qa inspect <run_id>
agentic-qa resume <run_id> approve --artifact all --reason "人工审核通过" --reviewed-by qa_owner
```

workspace 名称可以使用安全的中文、英文、数字、空格、点、下划线和连字符，但必须是单层目录名。

需要浏览器专家时，在对应的 `workspaces/<id>/workspace.yml` 中显式启用 Playwright MCP：

```yaml
execution:
  environments:
    staging:
      base_url_env: AGENTIC_QA_BASE_URL
      allowed_http_methods: [GET, HEAD, OPTIONS]
      allow_ui_mutations: true
      max_request_timeout_seconds: 10
mcp:
  playwright:
    schema_version: agentic-qa.harness.playwright-mcp.v1
    transport: stdio
    command: npx
    args: [-y, "@playwright/mcp@latest", --headless, --isolated]
    allowlist: [browser_navigate, browser_snapshot, browser_click, browser_type]
```

该入口只允许官方 `@playwright/mcp@latest` stdio 包或明确的 streamable HTTP URL，不接受
任意本地命令。Harness 会在每个新 run 开始时 initialize、list tools，并把 allowlist 过滤后的
Schema 快照写入该 run；崩溃恢复时实时清单必须与原快照一致。任何非分析执行都必须同时在
`workspace.yml` 登记测试环境，并由 `TaskRequest.execution_profile` 请求不超过该策略的权限；
UI 工具还必须在两处都设置 `allow_ui_mutations=True`。生产环境名称会被契约直接拒绝。本机需要
Node.js 18+；启动方式遵循 [Playwright MCP 官方配置](https://github.com/microsoft/playwright-mcp)。
通过 CLI 执行时使用例如
`agentic-qa run demo "验证测试站点" --artifact ui_test_draft --environment staging
--base-url-env AGENTIC_QA_BASE_URL --allow-ui-mutations`；workspace 策略或执行参数任一缺失时，
Playwright 调用都会被安全门拒绝。

运行中断后，使用 `agentic-qa resume <run_id>` 从同一 checkpoint 恢复。没有配置模型时，
`run` 会在创建候选前明确失败；离线评测使用录制响应，不会伪装成真实模型输出。

Harness 会自动使用 `deepseek-v4-flash` 处理常规结构化任务，用
`deepseek-v4-pro` 处理复杂主管规划、风险策略、长篇测试设计和失败分诊。规划与高推理专家启用
思考模式，长篇测试设计使用 Pro 但关闭思考模式；路由决策记录在 run snapshot 和事件中，
但不保存模型的 `reasoning_content`。
可用 `AGENTIC_QA_MODEL_FLASH`、`AGENTIC_QA_MODEL_PRO` 覆盖两档模型；设置
`AGENTIC_QA_MODEL` 会把两档固定到同一个模型。单次模型请求默认 180 秒超时且不由 SDK
隐式重试，可通过 `AGENTIC_QA_MODEL_TIMEOUT_SECONDS` 调整；显式重试仍受 Harness 预算约束。

专家产物在写入 candidate 前会执行确定性格式与源证据语义校验；错误会连同具体缺失项反馈
给原专家，单任务最多自修复五次。无效内容不会落盘，仍失败时才由主管在全局重规划预算内
处理；预算耗尽后只生成明确标记的 partial，不伪装完成。

其他命令：

```text
agentic-qa agents list
agentic-qa skills list
agentic-qa tools list
agentic-qa eval run
```

旧 `prd/` 已退出版本控制并保持本机忽略；Harness 不迁移、不读取或改写它。向新 API
传入 `prd/...` 会明确报“旧工作区不受 Harness 支持”。

通用测试方法位于 `src/harness/knowledge/` 并由 Skill manifest 显式引用；项目需求、
OpenAPI 和历史证据应放入 `workspaces/<id>/sources/`。当前配置来源为 `.env.example`、
`workspace.yml`、声明式 manifest 和
`TaskRequest.execution_profile`，不设置无效的顶层配置目录。

## 文档

- [架构](docs/architecture.md)
- [Harness 契约](docs/harness-contracts.md)
- [工作区与产物版本](docs/artifact-versioning.md)
- [Review Gate](docs/review-gate.md)
- [RAG 设计](docs/rag-design.md)
- [路线图](docs/roadmap.md)
