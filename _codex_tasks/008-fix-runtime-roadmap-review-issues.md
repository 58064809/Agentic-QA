# 任务 008：修复 007 Runtime 路线审核问题

## 任务目标

修复 007 `docs: align production agent runtime roadmap` 审核中发现的文档一致性和校验脚本问题，确保后续真正进入 LangGraph Runtime 骨架实现前，Codex 不会因为规则冲突产生误判。

本任务是 007 的审核修复任务，不是 Runtime 骨架实现任务。完成本任务后，再继续创建或执行 Runtime 骨架任务。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不实现 LangGraph Runtime，不引入 LangGraph / LangChain 依赖。
4. 不新增 Web 平台、数据库、向量库或复杂服务。
5. 只修复文档规则冲突、校验脚本弱化问题和必要测试。
6. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 审核发现

### 问题 1：AGENTS.md 存在阶段冲突

当前 `AGENTS.md` 的“禁止事项”里仍然写着：

```text
不实现新的 Agent Runtime、工作流引擎、LLM Provider 或平台服务。
```

但 007 又新增了“第 2 阶段：LangGraph Runtime 驱动的轻量执行引擎”。这会导致 Codex 后续读取 `AGENTS.md` 时产生冲突：到底是永远不允许实现 Runtime，还是只有第 1 阶段 / 非 Runtime 任务不允许实现 Runtime。

### 修复要求

把该禁止项改成阶段化约束，例如：

```text
在第 1 阶段文档工作台任务或未明确授权的任务中，不实现新的 Agent Runtime、工作流引擎、LLM Provider 或平台服务。
```

并补充说明：

```text
只有当用户明确要求执行第 2 阶段 Runtime 任务，且任务文件明确授权时，才允许新增轻量 Runtime 骨架；Runtime 仍必须复用 workflows/、prompts/、rules/、skills/、knowledge/，不得替代声明式资产。
```

要求：

- 不要删除 Human-in-the-loop、路径、状态和产物规则。
- 不要让 Codex 理解成可以随意实现完整 Runtime。
- 要表达“默认禁止，明确 Runtime 任务才允许轻量实现”。

## 问题 2：文档一致性校验脚本的跳过条件过宽

当前 `scripts/validate_docs_consistency.py` 中：

```python
PLANNED_REFERENCE_MARKERS = ("待生成", "如生成", "可后续生成", "后续生成", " 或 ")
```

`" 或 "` 是非常泛化的中文连词，会导致一整行只要包含“或”，该行里的 Markdown 路径引用就完全跳过检查。这样会降低文档一致性检查的有效性。

### 修复要求

1. 从 `PLANNED_REFERENCE_MARKERS` 中移除 `" 或 "`。
2. 不要用泛化中文连词作为跳过条件。
3. 如果确实需要跳过规划类路径，应使用明确的标记，例如：
   - `待生成`
   - `如生成`
   - `可后续生成`
   - `后续生成`
   - `可选新增`
   - `后续任务中创建`
4. 确保 `docs/`、`workflows/` 等真实路径引用仍然会被检查。

## 问题 3：需要补一个回归测试防止校验弱化

请更新 `tests/unit/test_docs_consistency.py`，新增测试用例：

场景：Markdown 某一行包含中文“或”，同时包含一个不存在的仓库路径引用。

示例：

```markdown
这里可以读取 `docs/not-exist.md` 或 `docs/roadmap.md`。
```

预期：

- `validate_docs_consistency` 必须报告 `docs/not-exist.md` 不存在。
- 不能因为该行包含“或”就整行跳过。

## 建议修改文件

至少修改：

```text
AGENTS.md
scripts/validate_docs_consistency.py
tests/unit/test_docs_consistency.py
```

可选检查：

```text
README.md
COMMANDS.md
docs/architecture/production-agent-runtime-roadmap.md
```

如果这些文件没有发现新的冲突，可以不改。

## 验收命令

完成后尽量执行：

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

建议 Commit message：

```text
docs: fix runtime roadmap review issues
```

## 完成后的回复要求

必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复，只输出摘要，不粘贴完整文件或完整 diff。

完成回执必须包含：

1. 变更摘要。
2. 修改文件列表。
3. 是否修复 AGENTS.md 阶段冲突。
4. 是否移除 `" 或 "` 泛化跳过条件。
5. 是否新增包含“或”的路径引用回归测试。
6. 已执行的验收命令和结果。
7. 未执行命令及原因。
8. 待人工确认点。
9. 下一步建议。

## 下一步

本任务完成并审核通过后，再继续 Runtime 骨架任务。Runtime 骨架任务建议命名为：

```text
009-bootstrap-langgraph-runtime-skeleton.md
```