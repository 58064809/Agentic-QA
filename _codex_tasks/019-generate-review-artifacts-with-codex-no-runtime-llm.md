# 任务 019：不使用 Runtime LLM，直接生成下午评审用需求分析和测试用例

## 任务背景

真实需求已经完成 PDF 转 Markdown：

```text
prd/5月第二周运营活动核心需求-review/requirement.md
```

但 Runtime 的 OpenAI-compatible Provider 当前不稳定，用户决定今天先不使用 Runtime LLM，也就是不要通过 `--use-llm` 调用外部 Provider。

本任务目标是：由 Codex 直接读取仓库规则和目标 PRD 文本，生成下午评审用的需求分析和测试用例 Markdown 文件。

注意：这里的“不使用 LLM”是指不调用 Runtime 里的外部 LLM Provider，不执行 `--use-llm`。Codex 作为人工驱动的代码/文档执行助手，可以直接根据本地文件生成产物。

## 目标需求

目标 PRD 工作区：

```text
prd/5月第二周运营活动核心需求-review/
```

必须读取：

```text
prd/5月第二周运营活动核心需求-review/requirement.md
prd/5月第二周运营活动核心需求-review/api-doc.md  # 如果存在
prd/5月第二周运营活动核心需求-review/metadata.yml
```

同时读取必要规范：

```text
AGENTS.md
COMMANDS.md
rules/requirement-analysis-rules.md
rules/testcase-rules.md
rules/review-gate-rules.md
rules/artifact-path-rules.md
skills/requirement-decomposition-skill.md
skills/business-rule-extraction-skill.md
skills/test-design-skill.md
skills/boundary-value-analysis-skill.md
skills/scenario-modeling-skill.md
skills/state-transition-modeling-skill.md
skills/risk-based-testing-skill.md
knowledge/templates/requirement-analysis-template.md
knowledge/templates/testcase-template.md
```

## 输出文件

直接写入：

```text
prd/5月第二周运营活动核心需求-review/10-analysis/requirement-analysis.md
prd/5月第二周运营活动核心需求-review/20-testcases/testcases.md
```

如果目标文件已存在：

1. 先读取现有内容。
2. 如果是空文件、低质量草稿或未通过评审的草稿，可以直接覆盖。
3. 如果明显是人工已审核内容，先停止并提示用户确认。

## 需求分析输出要求

`requirement-analysis.md` 必须包含：

```markdown
---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
---

# 需求分析草稿

## 1. 需求背景与目标
## 2. 业务范围
## 3. 角色与权限
## 4. 主流程拆解
## 5. 分支流程与异常流程
## 6. 业务规则清单
## 7. 数据字段与状态流转
## 8. 接口与依赖系统
## 9. 测试范围建议
## 10. 风险点与影响面
## 11. 待确认问题
## 12. 需求到测试覆盖映射
```

要求：

- 必须结合 `requirement.md` 具体内容写，不要泛泛而谈。
- `业务规则清单` 必须是具体规则表，不能只有“待补充”。
- `待确认问题` 至少 5 条，且必须具体可回答。
- 如果需求中存在图片、原型图或图片引用，明确写入：当前未分析图片内容，只基于正文生成。
- 不得编造需求中没有的规则；不确定内容标记为待确认。

## 测试用例输出要求

`testcases.md` 必须包含：

```markdown
---
status: needs_human_review
artifact_type: testcase_draft
human_review_required: true
---

# 测试用例草稿

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
```

固定列：

```text
标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果
```

不允许新增“用例类型”列。

数量要求：

- 如果需求简单，不少于 15 条。
- 如果需求中等，不少于 30 条。
- 如果需求复杂，不少于 50 条。
- 本次“运营活动核心需求”通常应按中等或复杂需求处理，优先生成不少于 30 条；若活动规则较多，生成不少于 50 条。

覆盖要求：

- 主流程 P0。
- 活动配置/展示/领取/使用/下单/支付/退款/失效等主链路，按 PRD 实际内容确定。
- 用户角色、后台角色、权限差异。
- 活动状态流转。
- 活动时间边界。
- 活动库存、名额、次数、金额、门槛、优惠叠加等，如需求涉及。
- 必填、格式、边界值。
- 异常流程。
- 重复提交、幂等、防刷。
- 数据一致性。
- 老数据兼容和回归影响。
- 前后端展示一致性。
- 接口异常、弱网、超时或依赖失败。
- 埋点、消息、通知、日志、审计，如需求涉及。

每条用例要求：

- 标题明确业务场景。
- 优先级只能是 P0/P1/P2/P3。
- 前置条件写清账号、角色、活动状态、时间、数据准备等。
- 步骤可执行。
- 预期结果可验证，包含页面、接口、数据状态、日志或消息等观察点。

## 禁止事项

1. 不调用 `python -m runtime.cli ... --use-llm`。
2. 不调用外部 Provider。
3. 不提交真实 PDF、运行记录、`.venv/`、`.env`。
4. 不生成 API/UI 自动化脚本。
5. 不把图片内容当作已分析事实。

## 建议执行步骤

1. 读取目标 `requirement.md`。
2. 判断需求复杂度和业务模块。
3. 先生成完整需求分析。
4. 再基于需求分析生成测试用例。
5. 写入目标路径。
6. 自查 Markdown 表格是否能复制到飞书/Excel。
7. 自查是否有 P0、异常、边界、权限、状态、数据一致性等覆盖。

## 完成回执

完成后只输出摘要，包含：

1. 已生成文件路径。
2. 需求分析章节是否完整。
3. 测试用例数量。
4. P0/P1/P2/P3 大致分布。
5. 待人工确认的关键问题。
6. 未覆盖内容及原因。
