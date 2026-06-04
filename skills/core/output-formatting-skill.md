# 输出格式化 Skill

## 元数据

- Skill ID: S9
- 第一版必装: 是
- 适用阶段: Runtime QA Workflow

## 作用

输出 Markdown / JSON / YAML / XMind 数据结构

## 输入

分析草稿、用例草稿、结构化字段

## 输出

Markdown、JSON、YAML、可选 XMind 数据

## 执行步骤

- Markdown 输出必须带 Front Matter 和 needs_human_review
- 结构化伴随文件记录 schema_version、artifact_type、source_files、warnings、quality_errors
- 多产物 run-summary 必须列出 output_paths 和产物清单
- 禁止把完整大文件粘贴到 Chat，必须写入文件并返回路径

## 质量门

- 输出必须可追溯到 PRD、规则、历史知识或人工确认项。
- 不确定内容必须标记“待确认”“待补充”或“假设”。
- 不得输出纯模板、占位内容或未经确认的正式结论。
