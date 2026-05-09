# 任务 006：新增轻量文档一致性检查

## 任务目标

在 005 已统一 Codex 完成回执模板后，继续补一个轻量级仓库健康检查能力，用来发现文档化 Agentic QA 工作区里常见的断链、缺文件、模板缺关键段落等问题。

本任务不是自研测试平台，也不是自研 Agent Runtime，而是新增一个工程辅助脚本，帮助后续每次改 `AGENTS.md`、`COMMANDS.md`、`workflows/`、`tasks/`、`rules/`、`skills/`、`knowledge/templates/` 时，能快速检查基础结构是否还完整。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 尽量不自研，不创建 Runtime、LLM Provider、LangGraph、LangChain、LiteLLM、`agentic_qa/` 或 `src/agentic_qa/`。
4. 工程脚本只放 `scripts/`。
5. 检查逻辑保持轻量，不要做复杂解析器，不要引入数据库、Web 平台或额外服务。
6. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 背景

当前仓库已经形成了文件化 Agent、Workflow、Task、Prompt、Rules、Skills、Knowledge 和 PRD 工作区结构。后续快速迭代时，最容易出现的问题是：

- `COMMANDS.md` 或 workflow 中引用了不存在的文件。
- 关键目录被漏建或误删。
- 新增规则或模板缺少必要标题。
- Codex 输出规则和完成回执模板不一致。
- README 里的验收命令和实际脚本不匹配。

006 的目标是用一个轻量脚本先守住这些基础问题。

## 具体任务

### 1. 新增文档一致性检查脚本

新增：

`scripts/validate_docs_consistency.py`

建议检查内容：

1. 核心文件存在：
   - `README.md`
   - `AGENTS.md`
   - `COMMANDS.md`
   - `rules/codex-output-rules.md`
   - `knowledge/templates/codex-completion-summary-template.md`

2. 核心目录存在：
   - `workflows/`
   - `agents/`
   - `tasks/`
   - `prompts/`
   - `rules/`
   - `skills/`
   - `knowledge/`
   - `knowledge/templates/`
   - `prd/`
   - `scripts/`
   - `tests/`

3. Codex 输出规则必须包含：
   - `标准完成回执模板`
   - `变更摘要`
   - `修改文件`
   - `验收结果`
   - `待人工确认`
   - `下一步建议`

4. 完成回执模板必须包含：
   - `变更摘要`
   - `修改文件`
   - `验收结果`
   - `待人工确认`
   - `下一步建议`
   - `未执行命令必须说明原因`

5. 可选增强：
   - 扫描 Markdown 文件中形如 `` `path/to/file.md` `` 的仓库内相对路径，若路径明显指向仓库文件但不存在，则输出警告或错误。
   - 为避免误报，只检查以这些前缀开头的路径：`workflows/`、`agents/`、`tasks/`、`prompts/`、`rules/`、`skills/`、`knowledge/`、`prd/`、`scripts/`、`tests/`、`_codex_tasks/`。

要求：

- 脚本可直接执行：

```bash
python scripts/validate_docs_consistency.py
```

- 通过时返回 exit code 0。
- 失败时返回非 0，并打印中文错误列表。
- 不要引入复杂依赖，优先使用 Python 标准库。

### 2. 补充单元测试

新增或更新测试文件，例如：

`tests/unit/test_docs_consistency.py`

至少覆盖：

- 当前仓库执行 `validate_docs_consistency` 结果通过。
- 缺少核心文件时能返回错误。
- `rules/codex-output-rules.md` 缺少关键标题时能返回错误。

如果为了可测试性需要把脚本拆成函数，允许在 `scripts/validate_docs_consistency.py` 中提供：

- `validate_docs_consistency(repo_root: Path) -> list[str]`
- `main() -> int`

### 3. 更新 README

在 `快速开始` 或 `Codex 输出约定` 附近补充新命令：

```bash
python scripts/validate_docs_consistency.py
```

说明它用于检查仓库文档结构、规则模板和关键引用是否完整。

### 4. 更新 005 相关文档引用

如有必要，轻微更新：

- `rules/codex-output-rules.md`
- `knowledge/templates/codex-completion-summary-template.md`

但不要大改 005 已完成内容，006 的重点是校验能力。

## 验收命令

执行：

```bash
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/sample-login-requirement
python scripts/run_pytest.py
pytest
ruff check .
```

如果某个命令未执行，完成回执中必须说明原因，不能写成通过。

## 提交要求

直接提交到 `master`。

Commit message：

```text
chore: add lightweight docs consistency check
```

## 完成后的回复要求

必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复，只输出摘要，不粘贴完整文件或完整 diff。
