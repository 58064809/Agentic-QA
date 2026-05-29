# QA 方法库

> 给 QA 工程师阅读和学习的方法论文档，覆盖测试设计全流程。

## 概览

`qa-methods/` 是 QA 团队的**方法论文库**，包含 14 篇结构化方法文档，按用途分三类：

### Ⅰ. 测试方法论（测试设计技术）

| 文件 | 说明 | 难度 |
|------|------|:----:|
| `equivalence-partitioning-skill.md` | 等价类划分 — 输入空间降维 | ★★☆ |
| `boundary-value-analysis-skill.md` | 边界值分析 — 边界精度测试 | ★★☆ |
| `state-transition-modeling-skill.md` | 状态迁移建模 — 状态驱动测试 | ★★★ |
| `scenario-modeling-skill.md` | 场景建模 — 端到端用户路径 | ★☆☆ |
| `risk-based-testing-skill.md` | 基于风险的测试 — 优先级决策 | ★★★ |
| `test-design-skill.md` | 测试设计综合 — 方法组合策略 | ★★★ |

### Ⅱ. 分析流程（输入分析）

| 文件 | 说明 | 难度 |
|------|------|:----:|
| `requirement-decomposition-skill.md` | 需求拆解 — 需求到分析模型 | ★★☆ |
| `business-rule-extraction-skill.md` | 业务规则提取 — 从需求到规则表 | ★★☆ |
| `api-contract-analysis-skill.md` | API 契约分析 — 接口级断言设计 | ★★☆ |
| `failure-log-analysis-skill.md` | 失败日志分析 — 执行失败分类诊断 | ★★☆ |

### Ⅲ. 产物编写（输出标准化）

| 文件 | 说明 | 难度 |
|------|------|:----:|
| `bug-report-writing-skill.md` | 缺陷报告撰写 — 可复现缺陷描述 | ★☆☆ |
| `qa-report-writing-skill.md` | QA 报告撰写 — 测试汇总与风险评估 | ★☆☆ |
| `pytest-api-test-skill.md` | pytest API 测试 — API 自动化最佳实践 | ★★☆ |
| `playwright-ui-test-skill.md` | Playwright UI 测试 — UI 自动化最佳实践 | ★★☆ |

## 典型阅读路径

```
新手 QA ──► 需求拆解 ──► 业务规则提取 ──► API 契约分析
               │
               ├──► 等价类划分 + 边界值分析  ──► 测试设计综合
               ├──► 状态迁移建模 ──► 测试设计综合
               └──► 场景建模 ──► 测试设计综合
                                       │
                                       ├──► pytest / Playwright 脚本编写
                                       ├──► 失败日志分析
                                       ├──► 缺陷报告撰写
                                       └──► QA 报告撰写
```

## 与其他目录的关系

```
prompts/       ── 给 LLM 的提示词模板（机器使用）
qa-methods/    ── 给 QA 工程师的方法论文档（人类阅读）
.atomcode/skills/ ── 给 AI Agent 的执行指令（AI 执行）
```

> 💡 **提示**：`.atomcode/skills/` 中的 AI Skill 文件会引用本文档作为方法依据，
> 本文档更新后请同步确认关联 AI Skill 是否需调整。
