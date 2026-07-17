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
agentic-qa resume <run_id> approve --artifact all --reason "人工审核通过"
```

workspace 名称可以使用安全的中文、英文、数字、空格、点、下划线和连字符，但必须是单层目录名。

运行中断后，使用 `agentic-qa resume <run_id>` 从同一 checkpoint 恢复。没有配置模型时，
`run` 会在创建候选前明确失败；离线评测使用录制响应，不会伪装成真实模型输出。

Harness 会自动使用 `deepseek-v4-flash` 处理常规结构化任务，用
`deepseek-v4-pro` 处理复杂主管规划、风险策略、长篇测试设计和失败分诊。规划启用思考模式，常规专家任务
关闭思考模式；路由决策记录在 run snapshot 和事件中，但不保存模型的 `reasoning_content`。
可用 `AGENTIC_QA_MODEL_FLASH`、`AGENTIC_QA_MODEL_PRO` 覆盖两档模型；设置
`AGENTIC_QA_MODEL` 会把两档固定到同一个模型。

专家产物在写入 candidate 前会执行确定性格式校验；格式错误会连同具体缺失项反馈给原专家，
单任务最多自修复三次。无效内容不会落盘，仍失败时才由主管在全局重规划预算内处理。

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
OpenAPI 和历史证据应放入 `workspaces/<id>/sources/`。根 `knowledge/` 仅保留本地旧资料，
不会被 Harness 读取。当前配置来源为 `.env.example`、声明式 manifest 和
`TaskRequest.execution_profile`，不设置无效的顶层配置目录。

## 文档

- [架构](docs/architecture.md)
- [Harness 契约](docs/harness-contracts.md)
- [工作区与产物版本](docs/artifact-versioning.md)
- [Review Gate](docs/review-gate.md)
- [RAG 设计](docs/rag-design.md)
- [路线图](docs/roadmap.md)
