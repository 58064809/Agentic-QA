# AI-Assistant

个人 AI 测试助手。目标不是平台、知识库或多 Agent 系统，而是在 IDE / 终端里直接对话，让助手按短规则识别意图、加载最少上下文并执行测试相关工作。

## 能力

- 需求分析：读取需求包中的 PRD 和原型，输出测试视角分析。
- 测试用例生成：生成可执行 Markdown 表格，包含测试数据、步骤、预期和校验点。
- pytest 脚本生成：基于需求生成 pytest 骨架。
- pytest 执行：从自然语言提取 target / marker / keyword 并执行。
- pytest 结果分析：识别失败类型并给出排查建议。
- 日志分析：按文件或关键字搜索日志。

## 目录

- `AGENTS.md`: 项目级 AI 记忆，给 Codex / IDE 新会话读取。
- `agents/`: 助手角色定义。
- `rules/`: 意图规则和路由配置。
- `flows/`: 轻量流程定义。
- `skills/`: 技能说明，只放 `SKILL.md`。
- `actions/`: 技能对应的 Python 动作实现。
- `runtime/`: 意图识别、资源加载、文档发现、路由执行、结果保存。
- `tests/`: 回归测试。
- `workspace/requirements/`: 需求资料工作区。

`AGENTS.md` 和 `agents/*/AGENT.md` 不要混用：根目录 `AGENTS.md` 记录项目级约定和目录边界；`agents/*/AGENT.md` 是运行时可加载的具体角色定义。当前默认角色是 `agents/senior_test_engineer/AGENT.md`，后续如需多 agent，在 `agents/` 下新增独立目录即可。

## 需求资料放置

每个新需求一个独立目录：

```text
workspace/requirements/<requirement-name>/
  docs/        # PRD、需求说明
  prototype/   # 原型、截图、设计稿
  logs/        # 需求相关日志
  tests/       # 需求相关 pytest
  outputs/     # 助手自动保存的结果
```

当前示例需求在：

```text
workspace/requirements/deposit-management/
```

## 使用

```bash
python -m runtime.cli "帮我分析保证金需求，看看 PRD 和原型图"
python -m runtime.cli "帮我根据保证金需求生成测试用例"
python -m runtime.cli "执行 pytest tests"
python -m runtime.cli "分析日志 logs/app.log 关键字 timeout"
```

## 使用（Poetry 推荐）

本项目默认按 Poetry 管理依赖（可复现、便于 CI）。

```bash
pip install poetry
poetry install
poetry run python -m runtime.cli "帮我分析保证金需求，看看 PRD 和原型图"
```

运行测试：

```bash
poetry run pytest -q
```

默认使用项目下的 `workspace/`。如果要指定其他工作区：

```bash
python -m runtime.cli "帮我分析需求" D:\your-workspace
```

默认输出人可读 Markdown 摘要，并把完整结果保存到对应需求包的 `outputs/`。需要结构化结果时加 `--json`。

## 验证

```bash
pytest -q
```
