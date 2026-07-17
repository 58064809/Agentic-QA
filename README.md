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
    ),
)
```

## 当前能力

- 真实 LangGraph StateGraph、SQLite checkpoint、动态 `Send` 并行派发与崩溃恢复。
- 测试主管结构化规划、依赖检查、专家验收与有限重规划。
- 需求、风险、测试设计、API、UI、执行、失败分诊、报告和审核辅助专家。
- 声明式 Agent、Skill、Tool manifest；每个专家只看到 allowlist 中的工具。
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

$env:AGENTIC_QA_MODEL="<provider-model>"
$env:AGENTIC_QA_MODEL_BASE_URL="<openai-compatible-base-url>"
$env:AGENTIC_QA_MODEL_API_KEY_ENV="DEEPSEEK_API_KEY"
# 在本机环境中设置 DEEPSEEK_API_KEY；不要写入仓库。

agentic-qa workspace init demo
agentic-qa run demo "分析登录需求并生成测试用例"
agentic-qa inspect <run_id>
agentic-qa resume <run_id> approve --artifact all --reason "人工审核通过"
```

运行中断后，使用 `agentic-qa resume <run_id>` 从同一 checkpoint 恢复。没有配置模型时，
`run` 会在创建候选前明确失败；离线评测使用录制响应，不会伪装成真实模型输出。

其他命令：

```text
agentic-qa agents list
agentic-qa skills list
agentic-qa tools list
agentic-qa eval run
```

旧 `prd/` 已退出版本控制并保持本机忽略；Harness 不迁移、不读取或改写它。向新 API
传入 `prd/...` 会明确报“旧工作区不受 Harness 支持”。

## 文档

- [架构](docs/architecture.md)
- [Harness 契约](docs/harness-contracts.md)
- [工作区与产物版本](docs/artifact-versioning.md)
- [Review Gate](docs/review-gate.md)
- [RAG 设计](docs/rag-design.md)
- [路线图](docs/roadmap.md)
