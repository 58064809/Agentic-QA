# Agentic-QA Prompt 工程体系

## 概述

本目录包含 Agentic-QA 项目所有 Agent 角色的 Prompt 定义文件。每个 Prompt 对应一个 Agent 角色和一个 Workflow（工作流），指导 LLM 在特定上下文中执行 QA 任务。

## Prompt 体系结构

```text
prompts/
├── README.md                          # ← 本文档：Prompt 体系说明
├── semantic-router-prompt.md          # LLM 语义路由（核心入口）
├── requirement-analysis-prompt.md     # 需求分析 Agent
├── testcase-design-prompt.md          # 测试用例设计 Agent
├── api-test-generation-prompt.md      # API 测试生成 Agent
├── ui-test-generation-prompt.md       # UI 测试生成 Agent
├── test-execution-prompt.md           # 测试执行 Agent
├── failure-analysis-prompt.md         # 失败分析 Agent
├── bug-draft-prompt.md                # 缺陷草稿 Agent
├── report-generation-prompt.md        # QA 报告生成 Agent
├── archive-prompt.md                  # 归档 Agent
└── runtime-testcase-generation-prompt.md  # Runtime 测试用例生成 Agent（LangGraph 闭环）
```

### Prompt 与 Workflow 映射

| Prompt | Workflow | Agent 角色 | 阶段 |
|--------|----------|-----------|------|
| `semantic-router-prompt.md` | 路由层 | Runtime Agent | 入口 |
| `requirement-analysis-prompt.md` | 01-requirement-analysis-workflow.md | Requirement Analysis Agent | 需求分析 |
| `testcase-design-prompt.md` | 02-testcase-generation-workflow.md | Testcase Design Agent | 用例设计 |
| `api-test-generation-prompt.md` | 03-api-test-generation-workflow.md | API Test Generation Agent | API 自动化 |
| `ui-test-generation-prompt.md` | 04-ui-test-generation-workflow.md | UI Test Generation Agent | UI 自动化 |
| `test-execution-prompt.md` | 05-test-execution-workflow.md | Test Execution Agent | 测试执行 |
| `failure-analysis-prompt.md` | 06-failure-analysis-workflow.md | Failure Analysis Agent | 失败分析 |
| `bug-draft-prompt.md` | 07-bug-draft-workflow.md | Bug Draft Agent | 缺陷草稿 |
| `report-generation-prompt.md` | 08-report-generation-workflow.md | Report Generation Agent | QA 报告 |
| `archive-prompt.md` | 09-archive-workflow.md | Archive Agent | 归档 |
| `runtime-testcase-generation-prompt.md` | 10-runtime-testcase-generation-workflow.md | Runtime 测试用例生成 Agent | LangGraph 闭环 |

## Prompt 结构规范

每个 Prompt 必须包含以下结构（按顺序）：

| 章节 | 必填 | 说明 |
|------|------|------|
| Front Matter（YAML 元数据） | 否 | `version`、`last_updated`、`target_agent` |
| 标题（`# 名称 Prompt`） | 是 | 语义化标题 |
| `## 角色` | 是 | Agent 角色身份定义 |
| `## 任务` | 是 | 一句话说明任务 |
| `## 任务目标` | 是 | 2-3 句详细目标说明 |
| `## 输入` | 是 | 读取的文件和上下文 |
| `## 输出格式` | 是 | 输出结构和路径规范 |
| `## 必须参考的规则` | 是 | 引用的 rules、skills、knowledge 路径 |
| `## 质量要求` | 是 | 可检查的质量标准 |
| `## 先思考再输出（Chain of Thought）` | 是 | 分步骤推理过程 |
| `## 自检清单` | 是 | 输出前的格式和内容检查 |
| `## 禁止事项` | 是 | 边界和约束 |
| `## 待人工确认项` | 是 | 需要人工判断的内容 |
| `## 示例` | 推荐 | Few-shot 示例 |

## Prompt 设计原则

### 1. 角色明确
每个 Prompt 定义单一 Agent 角色，不混入多角色职责。

### 2. 任务边界清晰
- 明确「做什么」和「不做什么」
- 上游产物依赖链路清晰：Requirement → Testcase → Script → Execution → Analysis → Bug Draft → Report → Archive

### 3. 输出可检查
- 每项质量要求是可客观检查的（非主观描述）
- 自检清单覆盖格式、内容、来源三个维度
- 禁止事项明确避免常见错误

### 4. Chain of Thought（CoT）推理
每个 Prompt 包含「先思考再输出」章节，指导 LLM 在输出前分步骤推理。推理过程不写入输出产物。

### 5. Few-shot 示例
推荐提供 1-3 个具体输入输出示例，帮助 LLM 理解预期输出格式和质量。

### 6. 人工确认门
每个 Prompt 在第 12-13 章节明确列出待人工确认项，确保 AI 不越过人工做出最终判断。

## Prompt 版本管理

### 版本号规则
- 格式：`v<major>.<minor>`
- major：结构改变（增删章节、重构 CoT）
- minor：内容优化（改进示例、调整措辞、增强质量要求）

### 变更流程
1. 修改 Prompt 文件
2. 更新文件内 Front Matter 的 `version` 和 `last_updated`
3. 更新 `prompts/README.md` 中的版本记录表
4. 如涉及多 Prompt 联动，同步更新相关 Prompt 的「相关 Prompt」章节

## Prompt 效果评估

### 评估维度
| 维度 | 说明 | 评估方法 |
|------|------|----------|
| 输出一致性 | 同输入多次执行是否产出相似结果 | 人工抽查 |
| 结构合规 | 输出是否符合指定格式和章节 | 自检清单验证 |
| 规则遵循 | 是否遵守禁止事项和约束 | 代码审查 |
| 质量达标 | 覆盖度、可执行性、可追溯性 | 审核人反馈 |
| 拒绝率 | 是否拒绝不合理输入 | 日志统计 |

### 迭代优化
- 基于审核人反馈优化 Prompt 措辞
- 出现系统性输出偏差时调整 CoT 步骤
- 新增需求时及时创建或更新对应 Prompt

## 跨 Prompt 依赖关系

```text
semantic-router-prompt
  │
  ▼
requirement-analysis-prompt ──────────────────────────────┐
  │                                                        │
  ▼                                                        │
testcase-design-prompt ──────────────────────────────┐    │
  │                                                    │    │
  ├──► api-test-generation-prompt ──┐                  │    │
  │                                  ▼                  │    │
  └──► ui-test-generation-prompt ──► test-execution-prompt │
                                         │                  │
                                         ▼                  │
                                   failure-analysis-prompt  │
                                         │                  │
                                         ├──► bug-draft-prompt
                                         │                  │
                                         └──► report-generation-prompt
                                                              │
                                                              ▼
                                                        archive-prompt
```

## 常见问题

### Q: 需要新增 Agent 怎么办？
1. 创建对应的 Workflow 文件（`workflows/XX-name-workflow.md`）
2. 创建对应的 Prompt 文件（`prompts/name-prompt.md`）
3. 更新 `AGENTS.md` 中的协作表
4. 更新 `COMMANDS.md` 中的路由表
5. 更新 `prompts/README.md` 中的映射表

### Q: 修改已有 Prompt 时需要注意什么？
- 保持与对应 Workflow 的输入输出一致
- 保持与上下游 Prompt 的接口兼容
- 更新版本号
- 通知相关审核人

### Q: 如何确保 Prompt 质量？
- 使用自检清单逐项检查
- 定期人工抽查输出产物质量
- 收集审核人反馈并迭代优化
- 版本控制记录变更历史

## 版本记录

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v1.0 | 初始 | 建立 9 个基础 Prompt + 1 个语义路由 + 1 个 Runtime 测试用例生成 Prompt |
