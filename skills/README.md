# Runtime Skills

`skills/` 是 Runtime 唯一的可编排 Skill 库，用来给 LLM 路由、RAG 召回、需求分析、测试设计、自动化生成和报告生成提供结构化能力说明。

## 分层结构

| 目录 | 作用 |
|---|---|
| `registry/` | Skill 注册表，声明必装 Skill、优先级、适用任务和文件路径 |
| `core/` | 需求理解、上下文构建、RAG 检索、输出格式化等通用能力 |
| `analysis/` | 需求拆解、测试范围拆解、风险识别、业务规则提取 |
| `test-design/` | 测试方法选择、用例生成、用例评审、等价类、边界值、场景法、状态迁移等 |
| `automation/` | API 契约分析、pytest API、Playwright UI 自动化生成 |
| `reporting/` | 失败日志分析、缺陷草稿、QA 报告生成 |
| `knowledge/` | 知识沉淀 |

## 第一版必装 Skill

注册表：`skills/registry/skills.yaml`

S1-S10 是 Runtime 第一版必装 Skill。Runtime 应优先读取注册表，再按任务类型加载相关 Skill 文件。

## 使用约束

- 新增 Skill 必须放入对应分层目录。
- 新增必装 Skill 必须登记到 `skills/registry/skills.yaml`。
- Workflow、Prompt、Agent 和 Runtime 代码中的 Skill 引用必须使用分层路径。
