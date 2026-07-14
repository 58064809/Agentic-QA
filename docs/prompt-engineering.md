# Prompt 工程与治理

本文档是 Agentic-QA Prompt 结构、命名、版本和依赖治理的唯一说明。Prompt 的运行时装配逻辑以 `runtime/llm/prompt_builder.py` 为程序事实源；Workflow 选择以 `workflows/runtime/*.workflow.yml` 和 `runtime/workflow/catalog.py` 为事实源。

## 设计边界

Prompt 只负责告诉模型如何理解上下文并输出候选内容，不负责：

- 选择 Workflow。
- 写入正式产物。
- 修改 Review Gate 状态。
- 执行 promote。
- 定义与 `runtime/workspace.py` 不同的路径。

确定性行为必须留在 Runtime、Schema、Validator 和 Writer 中。

## 当前 Prompt 清单

| 任务 | Prompt | Runtime Workflow |
|---|---|---|
| 语义路由 | `prompts/semantic-router-prompt.md` | Runtime intent router |
| 需求分析 | `prompts/requirement-analysis-prompt.md` | `workflows/runtime/requirement-analysis.workflow.yml` |
| 测试用例 | `prompts/testcase-design-prompt.md` | `workflows/runtime/testcase-generation.workflow.yml` |
| API 测试草稿 | `prompts/api-test-generation-prompt.md` | `workflows/runtime/api-test-draft.workflow.yml` |
| UI 自动化草稿 | `prompts/ui-test-generation-prompt.md` | `workflows/runtime/ui-test-draft.workflow.yml` |
| 接口发现报告 | `prompts/api-discovery.md` | `workflows/runtime/api-discovery-report.workflow.yml` |
| RAG 自动化用例 | `prompts/rag-automation-case-prompt.md` | `workflows/runtime/rag-automation-case.workflow.yml` |
| QA 报告 | `prompts/report-generation-prompt.md` | `workflows/runtime/qa-report.workflow.yml` |

未进入当前 Runtime Workflow 的 Prompt 不得被描述为已执行能力。

## 唯一正文原则

一个任务只能有一个 Prompt 正文。文件命名统一为 `<task>-prompt.md`；已有稳定名称的 `api-discovery.md` 暂作为该任务唯一正文。

禁止同时维护“规范版”“运行时辅助版”“兼容版”或同任务双文件。Runtime、测试和文档必须引用同一个文件。

## Prompt 最小结构

每个 Prompt 至少包含：

1. YAML Front Matter：`version`、`last_updated`、`target_agent`。
2. 角色与任务。
3. 输入来源。
4. 输出结构或 Schema。
5. 必须参考的 Rule、Skill 和 Knowledge。
6. 可检查的质量要求。
7. 禁止事项。
8. 待人工确认规则。
9. 上下游接口契约。
10. 版本记录。

只有在任务确实需要时才增加示例、FAQ 或覆盖维度，避免为了统一章节数量制造空内容。

## 路径契约

Prompt 不自行发明路径，统一引用 `rules/artifact-path-rules.md`。当前关键路径为：

| 数据 | 路径 |
|---|---|
| 需求输入 | `prd/<id>/input/requirement.md` |
| 接口输入 | `prd/<id>/input/api.md` |
| 元数据 | `prd/<id>/metadata.yml` |
| 候选索引 | `prd/<id>/runs/<run-id>/artifact-preview.md` |
| 候选正文 | `prd/<id>/runs/<run-id>/<artifact>.preview.md` |
| 正式产物 | `prd/<id>/artifacts/<artifact>.md` |
| 审核记录 | `prd/<id>/reviews/<artifact>.review.yml` |

`artifact-preview.md` 只作为候选索引，模型输出和 promote 必须面向具体 `<artifact>.preview.md`。

禁止继续引用旧工作区目录、旧元数据文件或旧测试用例文件名；发现后直接修复，不增加别名、fallback 或双写。

## 测试用例契约

测试用例主表固定为 11 列：

```text
用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | 测试步骤 | 预期结果 | 断言/证据 | 待确认项
```

该结构由 `runtime/graph/nodes/mvp_quality.py` 校验。Prompt、模板、Rule 和下游消费方必须保持一致。

## 上下文装配

`runtime/workflow/catalog.py` 决定每个任务允许加载的上下文文件，`runtime/llm/prompt_builder.py` 决定选择顺序、单文件预算、裁剪和最终系统指令。

治理要求：

- 不把整套仓库文档无差别塞入 Prompt。
- 优先输入需求、接口契约、当前候选和强规则。
- Skill、Knowledge 和解释性文档按任务选择。
- 被删除、重复或未执行的文档不得进入 Runtime context files。
- RAG 召回内容必须保留来源和不足告警。

## 版本策略

- 主版本：输出结构、Schema 或角色边界发生不兼容变化。
- 次版本：质量要求、上下文或示例发生兼容增强。
- 补丁版本：错别字、链接或表述修正。

Prompt 修改必须同步检查：

1. `runtime/llm/prompt_builder.py` 的实际输出要求。
2. 对应 Workflow DSL。
3. Runtime quality validator。
4. 上下游 artifact、review 和 Schema。
5. Prompt 回归测试。

## 质量验证

每个 Prompt 至少准备：

- 一条正常输入黄金用例。
- 一条输入缺失用例。
- 一条需求冲突或超范围指令用例。
- 一条防编造检查。
- 一条输出结构检查。

仓库级检查：

```bash
python scripts/validate_docs_consistency.py
python scripts/validate_docs_consistency.py --watch
pytest
ruff check .
```

严格校验会阻止重复 Prompt、旧 Workflow 引用、旧路径契约和 Runtime context 悬空文件进入主分支。

## 新增或修改 Prompt

1. 确认任务已存在或需要新增当前 Runtime Workflow。
2. 创建或修改唯一 Prompt 正文。
3. 更新 `runtime/workflow/catalog.py` 的 context files。
4. 更新 `prompts/README.md` 索引。
5. 增加或更新 Prompt/输出质量测试。
6. 运行文档契约检查、pytest 和 ruff。
7. 删除被替代文件，不保留兼容副本。
