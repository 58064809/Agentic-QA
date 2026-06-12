---
name: project-conventions
description: Agentic-QA 项目约定知识库 — 目录架构、状态流转、LLM 边界、产物路径、命名规则
version: v3.0
last_updated: 2025-07-19
user_invocable: false
disabled_model_invocation: false
related_skills: [code-reviewer, gen-test, security-reviewer, github-actions]
---

# Agentic-QA 项目约定 (v3.0)

## 1. 项目全景

```
Agentic-QA/
├── agents/              # Agent 角色与职责边界
├── docs/                # 架构、路线图、项目说明
├── knowledge/           # 方法论、模板、规则集、历史经验
├── prd/                 # 需求工作区 + 产物目录（按 ID 组织）
│   └── <id>/
├── prompts/             # Prompt 工程模板（CoT + 版本管理）
├── rules/               # 路径、命名、状态、审核、专项规则
├── skills/              # 本目录（Skill 体系）
├── workflows/           # 声明式 QA 工作流
├── tests/               # 测试目录
│   ├── unit/            # 单元测试（pytest）
│   └── integration/     # 集成测试
└── runtime/             # LangGraph 运行时（可选）
```

## 2. PRD 产物标准路径

```
prd/<id>/
├── input/requirement.md                # 需求文档
├── input/api.md                    # 接口说明（可选）
├── workspace.yml                  # 元数据（id, title, status, owner, created_at）
├── analysis/
│   └── requirement-analysis.md   # 需求分析
├── cases/
│   └── test-cases.md              # 测试用例（功能 + 边界 + 异常）
├── automation/api/
│   └── generated/                # API 自动化脚本（pytest + requests）
├── execution/runs/         # 执行结果（JSON / 日志）
├── defects/          # 失败分析
├── report/
│   └── qa-review.md        # QA 报告草稿
├── archive/                   # 归档（只读快照）
└── exports/                      # 对外评审导出（可中文命名）
```

## 3. 状态流转

```
draft ──(提交审核)──> needs_human_review ──(批准)──> approved
                          │                              │
                      (打回)                          (归档)
                          ↓                              ↓
                        draft                        archived
```

- 产物创建默认状态：`draft`
- AI 完成后标记：`needs_human_review`
- 人工审核后可设为：`approved` 或打回 `draft`
- 历史版本归档为：`archived`

## 4. 核心工作模式

```
AI 生成 → 人工审核 → AI 执行 → 人工确认 → AI 归档
             ↑                         ↑
         Human-in-the-loop       决策留给人
```

### Human-in-the-loop 规则
- 所有生成产物必须经人审核后才能进入下一步
- 关键决策（批准/打回/终止）必须由人做出
- AI 不得自动进入下一阶段

## 5. LLM 使用边界

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| API Key | `FREEMODEL_API_KEY` | — | 必填 |
| Base URL | `FREEMODEL_BASE_URL` | — | 兼容 OpenAI SDK |
| Model | `FREEMODEL_MODEL` | — | 支持 GPT / DeepSeek 等 |
| LLM 开关 | `--use-llm` | 关闭 | 默认不启用 LLM |

- Runtime 默认**不启动 LLM**，需显式传 `--use-llm`
- 未启用 LLM 时降级生成**确定性评审级草稿**（基于规则 + 模板）
- Prompt 调用遵循 `prompts/README.md` 中的体系

## 6. 文件命名规则

| 实体 | 规则 | 示例 |
|------|------|------|
| 需求分析 | `<阶段编号>-<英文描述>.md` | `analysis/requirement-analysis.md` |
| 测试用例 | `test-cases.md` | — |
| API 测试 | `test_<target>.py` | `test_user_api.py` |
| 测试数据 | `test_<target>.json` | `test_user_api.json` |
| 报告草稿 | `qa-review.md` | — |
| 导出文件 | 中文名（面向业务方） | `用户管理模块测试报告.md` |

## 7. 测试约定

- 框架：pytest 7+
- 目录：`tests/unit/` 放单元测试，`tests/integration/` 放集成测试
- 命名：`test_<target>.py`，类名 `Test<Target>`，方法 `test_<scenario>`
- CI 流程：`ruff check . && pytest tests/`
- 覆盖率要求：新增代码覆盖率 ≥ 80%（仅统计 `runtime/` 和 `agent/` 目录）

## 8. 跨技能引用

| 相关 Skill | 用途 |
|------------|------|
| [code-reviewer](../code-reviewer/SKILL.md) | 检查代码是否符合以上约定 |
| [gen-test](../gen-test/SKILL.md) | 按以上测试规范生成测试 |
| [security-reviewer](../security-reviewer/SKILL.md) | 审查项目安全合规 |
| [github-actions](../github-actions/SKILL.md) | CI 配置遵循以上约定 |
