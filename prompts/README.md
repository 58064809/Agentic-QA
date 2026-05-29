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

## Prompt 统一结构规范（v2.0）

每个 Prompt **必须**按以下顺序包含全部 14 个章节。缺一不可。

| # | 章节 | 必填 | 说明 |
|---|------|:----:|------|
| 0 | `YAML Front Matter` | ✅ | `version`、`last_updated`、`target_agent` |
| 1 | `# 标题` | ✅ | `# XXX Prompt` 语义化标题 |
| 2 | `## 角色` | ✅ | Agent 角色身份定义，一句话说清是谁 |
| 3 | `## 任务` | ✅ | 一句话说明任务，用主动句式 |
| 4 | `## 任务目标` | ✅ | 2-3 句详细目标说明，不可写「请生成高质量输出」等空话 |
| 5 | `## 输入` | ✅ | 读取的文件、上下文来源、前置产物路径 |
| 6 | `## 输出格式` | ✅ | 输出结构、列定义、路径规范、Front Matter 模板 |
| 7 | `## 必须参考的规则与资产` | ✅ | 引用的 rules、qa-methods、knowledge 文件列表 |
| 8 | `## 质量要求` | ✅ | 编号列表，每条可衡量、可检查 |
| 9 | `## 先思考再输出（Chain of Thought）` | ✅ | 推理步骤，LLM 在内部执行，不写入输出 |
| 10 | `## 自检清单` | ✅ | 输出前的可勾选检查表（表格格式） |
| 11 | `## 禁止事项` | ✅ | 明确禁止的行为和边界 |
| 12 | `## 接口契约` | ✅ | 与上下游 Prompt 的数据交换协议 |
| 13 | `## 常见问题（FAQ）` | ✅ | 2-3 个高频问题 |
| 14 | `## 示例` | ✅ | 输入→输出完整示例（至少 1 个） |

### 版本策略

- 主版本 +1（如 v1→v2）：结构变更（增删章节、重构 CoT）
- 次版本 +1（如 v1.1→v1.2）：内容修订（质量要求、示例更新）
- 补丁 +1（如 v1.1→v1.1.1）：小修补（错别字、路径修正）

## 接口契约规范

每个 Prompt 的 `## 接口契约` 章节必须用以下格式定义与上下游的数据交换：

### 上游（输入依赖）
| 数据项 | 来源 Prompt | 文件路径 | 说明 |
|--------|-----------|---------|------|
| ... | ... | ... | ... |

### 下游（输出消费方）
| 数据项 | 消费方 Prompt | 文件路径 | 说明 |
|--------|-------------|---------|------|
| ... | ... | ... | ... |

### 关键约束
- 列出本 Prompt 对上游数据的依赖条件
- 列出本 Prompt 对下游的承诺

## 示例规范

每个 Prompt 的 `## 示例` 必须使用以下结构：

### 输入
（摘录或简化描述输入内容，注明来源文件）

### 输出
（摘录关键输出部分，显示格式和内容质量）

### 关键要点说明
（解释示例中体现的质量要求、边界处理或常见误区）

## Prompt 治理原则

1. **声明式优先**：引用 rules/qa-methods/knowledge 资产，但不内联抄写它们的内容
2. **可测试性**：每个质量要求必须可检查（可勾选、可自动化或可人工判断）
3. **版本对齐**：版本变更必须同时更新 README 中的版本记录表
4. **一致性**：相同语义章节在不同 Prompt 中的命名和结构必须一致
5. **最小化**：不写「高质量」「考虑周全」等不可衡量的要求

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
2. 创建对应的 Prompt 文件（`prompts/name-prompt.md`）— 必须遵循 14 章结构
3. 更新 `AGENTS.md` 中的协作表
4. 更新 `COMMANDS.md` 中的路由表
5. 更新 `prompts/README.md` 中的映射表和版本记录

### Q: 修改已有 Prompt 时需要注意什么？
- 保持与对应 Workflow 的输入输出一致
- 保持与上下游 Prompt 的接口兼容（更新接口契约）
- 按版本策略更新版本号
- 更新 `prompts/README.md` 的版本记录

### Q: 如何确保 Prompt 质量？
- 使用自检清单逐项检查 14 章节是否完整
- 每个质量要求本身可衡量、可验证
- 定期人工抽查输出产物质量
- 收集审核人反馈并迭代优化

### Q: 14 个章节必须全部实现吗？
是的。v2.0 标准要求全部 14 章节必填。如果某个 Prompt 没有上下游（如 archive），接口契约章节写「无下游」或「无上游」但不省略。

## 版本记录

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v2.0 | 2025-07-01 | 统一 14 章结构规范；新增接口契约、FAQ、Chain of Thought/自检清单/禁止事项全补齐；重命名 skills/ → qa-methods/ |
| v1.0 | 初始 | 建立 9 个基础 Prompt + 1 个语义路由 + 1 个 Runtime 测试用例生成 Prompt |
