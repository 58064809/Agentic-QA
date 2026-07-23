# Agentic-QA 命令入口

本文面向使用 CLI 的人员。完整正文以 MkDocs 文档为准：

- [从零开始](docs/getting-started.md)：安装、配置、Source、Run、Candidate、Review 与发布。
- [CLI 参考](docs/cli-reference.md)：命令、参数、状态、Artifact 和退出码。
- [配置参考](docs/configuration.md)：环境变量、`workspace.yml`、RAG 与 PostgreSQL。
- [跨 AI 接入](docs/agent-integration.md)：Codex、Claude、Cursor 的 MCP 与请求文件入口。

使用 AI 生成测试用例时，把每项需求放在
`local-sources/requirements/<需求名>/`。该目录不会提交到 Git，并在首次运行项目时自动创建。Codex
注册 MCP 后可直接说：

> 分析 `D:\TestHome\Agentic-QA\local-sources\requirements\<需求名>` 并生成测试用例。

最短流程：

```powershell
Set-Location D:\TestHome\Agentic-QA
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

$env:DEEPSEEK_API_KEY = "<你的模型密钥>"
$env:PG_LOCAL_PASSWORD = "<你的 PostgreSQL 密码>"

python -m harness workspace create demo
Copy-Item D:\Docs\prd.md .\workspaces\demo\sources\
python -m harness run start demo "分析需求并生成测试用例"
```

`run start` 返回 `run_id`。后续查询、恢复和审核始终使用 `workspace_id + run_id`。Candidate 不会
自动发布；必须先检查质量报告，再通过人工 `run review` 选择 `raw` 或 `normalized` 版本。
