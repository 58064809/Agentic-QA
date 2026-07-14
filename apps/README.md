# Apps

`apps/` 只放入口适配器，不包含工作流逻辑。

- `apps/cli/`：调用 `runtime.cli` 的命令行入口。
- `apps/feishu_bot/`：飞书入口包；业务编排仍由 Runtime 负责。

所有入口必须复用 `workflows/runtime/*.workflow.yml`、Review Gate 和标准 PRD 路径。
