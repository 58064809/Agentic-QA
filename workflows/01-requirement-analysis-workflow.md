# 01 需求分析工作流

## 适用场景

用于定位 PRD、读取需求与接口文档，并生成需求分析草稿。

## 触发命令

- “分析 `prd/<id>` 的需求。”
- “定位 `<id>` 并拆解业务规则。”

## 主 Agent

Requirement Analysis Agent

## 辅助 Agent

Testcase Design Agent 可协助识别测试关注点。

## 必须读取

- `tasks/00-locate-requirement.md`
- `tasks/01-analyze-requirement.md`
- `prompts/requirement-analysis-prompt.md`
- `rules/artifact-path-rules.md`
- `rules/requirement-analysis-rules.md`
- `skills/requirement-decomposition-skill.md`
- `skills/business-rule-extraction-skill.md`
- `knowledge/templates/requirement-analysis-template.md`

## 输入文件

- `prd/<id>/requirement.md`
- `prd/<id>/api-doc.md`
- `prd/<id>/metadata.yml`

## 输出路径

- `prd/<id>/10-analysis/requirement-analysis.md`

## 执行步骤

1. 校验 PRD 工作区存在且结构完整。
2. 读取需求、接口文档和 metadata。
3. 提取明确需求、隐含规则、待澄清问题、状态和边界。
4. 识别风险与测试关注点。
5. 生成需求分析草稿并标记为 `needs_human_review`。

## 前置条件

- 目标 PRD 工作区存在，或用户明确要求先创建工作区。
- `requirement.md`、`api-doc.md`、`metadata.yml` 至少有可读草稿。
- 如果需求材料缺失，不生成臆测结论，只输出待补材料清单。

## 状态标记

- 输出文件顶部必须写 `status: needs_human_review`。
- 必须写 `human_review_required: true`。
- 不得把需求分析标记为 `approved`。

## 异常处理

- 需求名不明确时，列出候选 PRD 工作区并等待用户确认。
- 接口文档缺失时，仍可分析业务需求，但必须标记 API 规则待补充。
- 需求与接口文档冲突时，列入待确认问题，不自行裁决。

## 禁止事项

- 不修改原始需求。
- 不把假设写成事实。
- 不跳过人工审核直接生成正式用例。

## 验收标准

- 分析内容可追溯到输入材料。
- 待澄清问题明确。
- 输出路径符合规则。

## 人工审核点

- 需求理解是否准确。
- 业务规则、边界和风险是否完整。
