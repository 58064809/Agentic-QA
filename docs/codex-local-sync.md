# Codex 本地能力同步说明

本目录用于把当前机器上可共享、可复现的 Codex 能力带到项目里，便于在另一台电脑克隆仓库后继续开发。

## 已同步

- 本地 Codex 技能：`C:\Users\EDY\.codex\skills` -> `.agents/skills`
- 项目级 MCP 配置：`.codex/config.toml`
- 项目级插件启用清单：`.codex/config.toml`

## 未同步

以下内容是机器私有状态或缓存，不应提交：

- `~/.codex/auth.json`
- `~/.codex/history.jsonl`
- `~/.codex/*.sqlite`
- `~/.codex/logs*`
- `~/.codex/sessions/`
- `~/.codex/plugins/cache/`
- `~/.codex/.sandbox*`
- `~/.codex/.sandbox-secrets/`

## 在另一台电脑使用

1. 克隆仓库并进入项目根目录。
2. 安装开发依赖：`pip install -e ".[dev]"`。需要 FAISS、PostgreSQL、文档转换或飞书导入时，再按 README 安装对应 extra。
3. 确认 Node.js / npm 可用，因为 MCP server 通过 `npx` 启动。
4. 如需 GitHub MCP，先运行 `gh auth login`。
5. 如需 Slack、Gmail、Figma、Notion 等插件，按 Codex 插件授权流程在新机器上重新登录。
6. 从项目根目录启动 Codex，让它读取 `.codex/config.toml` 和 `.agents/skills`。

## 维护规则

- 新增通用技能时，放入 `.agents/skills/<skill-name>/`。
- 不提交个人 token、cookie、sqlite、日志、会话和插件缓存。
- 如果某个 MCP 依赖本机绝对路径，应改为项目相对路径或写入本机私有配置。
- 项目级 MCP npm 包必须固定版本，不使用未标版本或 `@latest`，升级后需重新执行项目校验。
- 插件本体不要从 `~/.codex/plugins/cache` 复制到仓库，只保留项目级启用清单。
