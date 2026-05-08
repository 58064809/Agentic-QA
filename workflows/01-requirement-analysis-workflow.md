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
