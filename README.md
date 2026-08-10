# Agentic-QA

Agentic-QA 是面向测试工作的模块化 Agent Harness：测试主管规划并派发专家任务，来源按 run 冻结，
质量策略只读校验 Candidate，LangGraph 在 Review Gate 暂停。只有人工批准与确定性 promote 均成功，
产物才会进入 `published/`。

## 最短启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,docs]" -c constraints.txt

$env:DEEPSEEK_API_KEY = "<你的模型密钥>"
python -m harness config init
# 编辑仓库根目录 agentic-qa.local.yml
python -m harness config doctor
python -m harness workspace create demo
```

`constraints.txt` 固定已验证的依赖组合；依赖安装完成后可运行
`\.\scripts\cold-start-check.ps1` 检查新机器环境。完整步骤见[从零开始](docs/getting-started.md)。

`agentic-qa.local.yml` 是 API、PostgreSQL、TestRail、Qase 及非密钥模型/RAG 参数的唯一人工配置
入口，并被 Git 忽略。只有模型实际 Key 和 RAG 实际 Key 仍从环境变量读取；CLI 不自动加载 `.env`。

本地需求统一放入 `local-sources/requirements/<需求名>/`。目录被 Git 忽略，并在首次运行 Harness
时自动创建；跨 AI 的 MCP 注册和一句话用法见[跨 AI 接入](docs/agent-integration.md)。

## 核心边界

| 边界 | 行为 |
|---|---|
| 来源 | run 启动时冻结；恢复时不重新读取 workspace 当前文件 |
| Candidate | create-only；raw 永不被策略或 Normalizer 覆盖 |
| 质量 | 通用策略默认启用；业务策略按注册名显式选择 |
| Review | Agent 没有批准能力；人工选择带 hash 的强类型版本后，系统才接受审核记录 |
| 发布 | Repository 复验 Manifest、质量报告和人工 Review 后确定性 promote |
| 恢复 | PostgreSQL 是唯一 LangGraph checkpoint，不提供 SQLite 或内存生产 fallback |

## 文档入口

| 读者 | 从这里开始 | 继续阅读 |
|---|---|---|
| CLI 使用者 | [从零开始](docs/getting-started.md) | [CLI 参考](docs/cli-reference.md)、[配置](docs/configuration.md) |
| AI 集成者 | [跨 AI 接入](docs/agent-integration.md) | MCP 与 YAML/JSON AgentRequest |
| Python 集成者 | [Harness 契约](docs/harness-contracts.md) | [Review Gate](docs/review-gate.md) |
| 维护者 | [架构](docs/architecture.md) | [存储与版本](docs/artifact-versioning.md)、[RAG](docs/rag-design.md) |
| 内容维护者 | [内容分类](content-audiences.yml) | 人类文档、运行时 AI、机器契约与编码 Agent 的边界 |

## 验证

```powershell
ruff check .
pytest -q
python -m build --wheel
```

公开 Harness v2 方法以 `src/harness/interfaces/facade.py` 和
[Harness 契约](docs/harness-contracts.md)为准。
