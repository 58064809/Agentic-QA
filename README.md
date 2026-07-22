# Agentic-QA

Agentic-QA 是面向测试工作的模块化 Agent Harness。测试主管规划并派发专家任务，质量策略验证
候选产物，LangGraph 在 Review Gate 暂停；只有人工批准和确定性 promote 成功后才发布。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

真实密钥和数据库密码只设置在本机环境中，不要写入仓库。完整变量说明见
[配置文档](docs/configuration.md)。生产执行只使用 PostgreSQL checkpoint，不提供 SQLite 或
内存 fallback。

```python
from harness import (
    ArtifactVariant,
    CreateWorkspaceCommand,
    Harness,
    ReviewDecision,
    ReviewRunCommand,
    StartRunCommand,
)

harness = Harness(".")
harness.create_workspace(CreateWorkspaceCommand(workspace_id="demo"))
snapshot = harness.start_run(
    StartRunCommand(workspace_id="demo", goal="分析登录需求并生成测试用例")
)

published = harness.review_run(
    ReviewRunCommand(
        workspace_id="demo",
        run_id=snapshot.run_id,
        decision=ReviewDecision(
            intent="approve",
            target_artifact="all",
            reason="人工审核通过",
            reviewed_by="qa-owner",
            versions=[
                candidate.version_ref(ArtifactVariant.RAW)
                for candidate in snapshot.candidates
            ],
        ),
    )
)
```

公开 v2 API 为 `create_workspace`、`start_run`、`stream_run`、`get_run`、`resume_run` 和
`review_run`。所有 run 操作使用 `workspace_id + run_id`；`resume_run` 只恢复崩溃执行，
`review_run` 专门处理人工审核。CLI 示例见 [COMMANDS.md](COMMANDS.md)。

## 架构

代码按 `domain`、`application`、`infrastructure`、`interfaces` 分层，`bootstrap.py` 是唯一
组合根。文件存储拆为 Workspace、Run/Event、Artifact/Review Repository；LangGraph 仅位于
workflow adapter。详细说明见[架构文档](docs/architecture.md)。

默认 workspace 只启用通用质量策略；业务策略通过 `quality_policies` 注册名显式选择。
测试用例固定 11 列，API 机器用例继续使用 `agentic-qa.api-cases.v1.1`。候选不可覆盖，修订创建
新 run。旧 workspace 与 `prd/` 数据不会迁移、读取或删除。

## 验证

```powershell
ruff check .
pytest -q
python -m build --wheel
```

GitHub Actions 使用 PostgreSQL service 验证 checkpoint 建表、interrupt、跨连接恢复和并发 run。
