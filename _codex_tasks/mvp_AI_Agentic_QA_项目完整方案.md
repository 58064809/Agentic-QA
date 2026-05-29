# AI Agentic QA 项目方案

## 1. 项目定位

AI Agentic QA 是一个面向企业内部测试场景的通用型 AI 测试辅助工具。

项目目标不是绑定某个具体业务系统，而是沉淀一套可迁移、可扩展、可公开维护的测试分析与用例生成引擎。

代码将放在个人 GitHub 公开仓库中，敏感数据、企业数据、生成数据、日志、向量库文件等通过 `.gitignore` 排除，确保后续更换公司后仍可继续复用。

---

## 2. 核心目标

第一版重点解决：

- 读取飞书云文档需求
- 支持手动输入 Markdown 需求
- 自动完成需求理解
- 自动识别用户意图
- 结合 RAG 召回测试规范、Prompt 模板、项目文档
- 通过 LangGraph 编排 Agent 工作流
- 生成需求分析、风险分析、测试点、测试用例
- 输出适合人类评审的 Markdown 文档
- 输出适合 Agent 二次处理的 YAML / JSON 结构化数据

---

## 3. 第一版 MVP 范围

### 3.1 支持入口

第一版优先支持：

- PyCharm / Cursor 中运行
- CLI 命令行调用

预留但暂不实现：

- 飞书 Bot
- Web 页面

### 3.2 支持输入

第一版支持：

- 飞书云文档链接
- Markdown 文本

暂不支持：

- PDF
- Word
- Excel
- 飞书多维表格
- 飞书 Wiki
- 图片 OCR

### 3.3 支持输出

第一版输出：

- 需求分析 Markdown
- 风险分析 Markdown
- 测试点 Markdown
- 测试用例 Markdown
- 测试用例结构化 YAML
- 测试用例结构化 JSON

用例可视化推荐：

- 第一版优先使用 Markdown + Mermaid
- 后续再考虑 XMind 导出

---

## 4. 总体工作流

```text
用户输入飞书文档链接 / Markdown 文本
↓
文档解析
↓
需求内容清洗
↓
意图识别
↓
RAG 召回
↓
Agent 路由
↓
Skill 执行
↓
Prompt 生成
↓
阶段性结果校验
↓
人工确认 Checkpoint
↓
生成最终产物
↓
输出 Markdown / YAML / JSON
```

---

## 5. 核心设计原则

### 5.1 工作流优先，不做失控 Agent

项目不采用 AutoGPT 式无限自主 Agent。

核心原则：

```text
Workflow + State 是大脑
Agent 是专家节点
Skill 是可复用能力
Prompt 是生成策略
RAG 是上下文增强
```

### 5.2 第一版采用有限状态工作流

使用 LangGraph 编排固定流程。

每个节点职责明确：

- 输入是什么
- 输出是什么
- 是否需要 RAG
- 是否需要 LLM
- 是否需要人工确认
- 是否进入下一节点

### 5.3 模型不绑定

第一版必须设计 LLM 抽象层。

支持后续接入：

- DeepSeek
- Claude API
- OpenAI Compatible API
- 本地模型
- 其他模型

业务逻辑中不得直接依赖具体模型 SDK。

---

## 6. 推荐技术栈

| 模块 | 技术 |
|---|---|
| 语言 | Python |
| 工作流编排 | LangGraph |
| LLM 抽象 | 自定义 Provider |
| RAG | FAISS / Chroma 二选一 |
| 文档解析 | 飞书开放 API + Markdown Loader |
| 配置管理 | YAML + `.env` |
| 输出格式 | Markdown / YAML / JSON |
| CLI | Typer / Click |
| 日志 | Loguru / logging |
| 测试框架 | Pytest |

---

## 7. 项目目录结构

```text
ai-agentic-qa/
│
├── apps/                       # 入口层
│   ├── cli/
│   │   └── main.py
│   ├── pycharm/
│   │   └── run_analysis.py
│   └── feishu_bot/
│       └── README.md
│
├── core/                       # 核心运行时
│   ├── workflow/
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   └── edges.py
│   ├── state/
│   │   └── agent_state.py
│   ├── runtime/
│   │   └── runner.py
│   └── checkpoint/
│       └── human_checkpoint.py
│
├── agents/
│   ├── intent_agent.py
│   ├── requirement_agent.py
│   ├── risk_agent.py
│   ├── test_point_agent.py
│   ├── testcase_agent.py
│   └── review_agent.py
│
├── skills/
│   ├── requirement_parser.py
│   ├── risk_analyzer.py
│   ├── test_point_generator.py
│   ├── testcase_generator.py
│   ├── markdown_formatter.py
│   └── schema_validator.py
│
├── prompts/
│   ├── system/
│   ├── agents/
│   ├── skills/
│   └── templates/
│
├── rag/
│   ├── loaders/
│   ├── splitter/
│   ├── retriever/
│   ├── embedding/
│   └── vector_store/
│
├── integrations/
│   ├── feishu/
│   │   ├── client.py
│   │   └── doc_loader.py
│   ├── llm/
│   │   ├── base.py
│   │   ├── deepseek_provider.py
│   │   ├── claude_provider.py
│   │   └── openai_compatible_provider.py
│   └── exporters/
│       ├── markdown_exporter.py
│       ├── yaml_exporter.py
│       └── json_exporter.py
│
├── knowledge/
│   ├── standards/
│   ├── prompts/
│   ├── examples/
│   └── project_docs/
│
├── outputs/
├── logs/
├── vector_store/
│
├── configs/
│   ├── config.example.yaml
│   └── model.example.yaml
│
├── tests/
│
├── .env.example
├── .gitignore
├── README.md
└── pyproject.toml
```

---

## 8. 核心状态结构 AgentState

LangGraph 的核心是 State。

建议第一版状态结构如下：

```python
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class AgentState(BaseModel):
    task_id: str

    # 输入
    input_type: str
    input_source: str
    raw_content: str
    cleaned_content: Optional[str] = None

    # 意图识别
    user_intent: Optional[str] = None
    intent_confidence: Optional[float] = None

    # RAG
    rag_queries: List[str] = []
    retrieved_contexts: List[Dict[str, Any]] = []

    # 中间结果
    requirement_summary: Optional[str] = None
    requirement_items: List[Dict[str, Any]] = []
    risk_analysis: List[Dict[str, Any]] = []
    test_points: List[Dict[str, Any]] = []
    test_cases: List[Dict[str, Any]] = []

    # 人工确认
    need_human_confirm: bool = False
    human_feedback: Optional[str] = None
    confirmed_nodes: List[str] = []

    # 输出
    markdown_output: Optional[str] = None
    yaml_output: Optional[str] = None
    json_output: Optional[str] = None

    # 流程控制
    current_node: Optional[str] = None
    next_node: Optional[str] = None
    errors: List[str] = []
    metadata: Dict[str, Any] = {}
```

---

## 9. LangGraph 节点设计

第一版节点：

```text
load_input_node
↓
clean_document_node
↓
intent_recognition_node
↓
rag_retrieve_node
↓
requirement_analysis_node
↓
human_confirm_requirement_node
↓
risk_analysis_node
↓
test_point_generation_node
↓
testcase_generation_node
↓
review_node
↓
export_node
```

### 9.1 节点职责

| 节点 | 职责 |
|---|---|
| load_input_node | 读取飞书文档或 Markdown |
| clean_document_node | 清洗需求内容 |
| intent_recognition_node | 判断用户想做需求分析、用例生成还是补充分析 |
| rag_retrieve_node | 召回测试规范、Prompt 模板、项目文档 |
| requirement_analysis_node | 生成需求摘要和结构化需求点 |
| human_confirm_requirement_node | 人工确认需求理解是否正确 |
| risk_analysis_node | 生成风险分析 |
| test_point_generation_node | 生成测试点 |
| testcase_generation_node | 生成测试用例 |
| review_node | 检查完整性、重复性、优先级合理性 |
| export_node | 输出 Markdown / YAML / JSON |

---

## 10. 人工确认 Checkpoint 设计

人工确认不是审批，而是防止 AI 理解偏差。

### 10.1 Checkpoint 1：需求理解确认

系统输出：

```markdown
## 需求理解确认

我理解的需求如下：

1. xxx
2. xxx
3. xxx

请确认是否继续：

- 输入 `继续`：进入风险分析
- 输入 `修改：xxx`：补充或纠正需求理解
- 输入 `退出`：终止任务
```

### 10.2 Checkpoint 2：测试范围确认

系统输出：

```markdown
## 测试范围确认

本次计划覆盖：

- 功能主流程
- 异常流程
- 权限校验
- 数据校验
- 兼容性
- 边界值

请确认是否继续。
```

### 10.3 第一版建议

第一版只做一个 Checkpoint：

```text
需求理解确认
```

后续再增加：

- 测试范围确认
- 风险点确认
- 用例评审确认

---

## 11. RAG 知识库设计

### 11.1 第一版知识来源

```text
knowledge/
├── standards/
│   ├── test_case_standard.md
│   ├── priority_rule.md
│   └── risk_analysis_rule.md
│
├── prompts/
│   ├── requirement_analysis.md
│   ├── risk_analysis.md
│   └── testcase_generation.md
│
├── examples/
│   ├── good_test_cases.md
│   └── bad_test_cases.md
│
└── project_docs/
    └── README.md
```

### 11.2 第一版 RAG 策略

先用简单方案：

```text
Markdown 文档
↓
Chunk 切分
↓
Embedding
↓
FAISS / Chroma
↓
TopK 召回
↓
拼接到 Prompt 上下文
```

暂不做：

- GraphRAG
- 多路召回
- 知识图谱
- 自动知识抽取
- 复杂 Memory

---

## 12. Agent 设计

### 12.1 IntentAgent

职责：

- 判断用户输入意图
- 判断是否需要生成用例
- 判断是否需要风险分析
- 判断是否需要补充需求理解

输出：

```json
{
  "intent": "generate_test_cases",
  "confidence": 0.92,
  "required_agents": [
    "requirement_agent",
    "risk_agent",
    "test_point_agent",
    "testcase_agent"
  ]
}
```

### 12.2 RequirementAgent

职责：

- 解析需求背景
- 提取功能点
- 提取角色
- 提取流程
- 提取规则
- 提取异常场景

### 12.3 RiskAgent

职责：

- 分析功能风险
- 分析数据风险
- 分析兼容性风险
- 分析权限风险
- 分析接口风险
- 分析异常流程风险

### 12.4 TestPointAgent

职责：

- 根据需求和风险生成测试点
- 按模块、功能、场景组织
- 输出结构化测试点

### 12.5 TestCaseAgent

职责：

- 根据测试点生成测试用例
- 生成符合标准格式的用例
- 输出 Markdown / YAML / JSON

### 12.6 ReviewAgent

职责：

- 检查用例是否遗漏主流程
- 检查是否缺少异常场景
- 检查优先级是否合理
- 检查步骤和预期是否清晰
- 检查是否存在重复用例

---

## 13. Skill 设计

Skill 是可复用能力，不等于 Prompt。

### 13.1 第一版 Skill

```text
skills/
├── requirement_parser.py
├── risk_analyzer.py
├── test_point_generator.py
├── testcase_generator.py
├── markdown_formatter.py
├── yaml_formatter.py
├── json_formatter.py
└── schema_validator.py
```

### 13.2 Skill 示例

```python
def normalize_test_case(raw_case: dict) -> dict:
    return {
        "title": raw_case.get("title", ""),
        "priority": raw_case.get("priority", "P2"),
        "preconditions": raw_case.get("preconditions", []),
        "steps": raw_case.get("steps", []),
        "expected_results": raw_case.get("expected_results", []),
    }
```

---

## 14. Prompt 管理设计

### 14.1 Prompt 目录

```text
prompts/
├── system/
│   └── qa_system.md
├── agents/
│   ├── intent_agent_v1.md
│   ├── requirement_agent_v1.md
│   ├── risk_agent_v1.md
│   ├── test_point_agent_v1.md
│   └── testcase_agent_v1.md
└── templates/
    ├── markdown_report_template.md
    └── testcase_template.md
```

### 14.2 Prompt 版本管理

每个 Prompt 必须带版本：

```text
requirement_agent_v1.md
requirement_agent_v2.md
```

后续方便比较效果。

---

## 15. 输出格式设计

### 15.1 Markdown 需求分析报告

```markdown
# 需求分析报告

## 一、需求摘要

## 二、核心业务流程

## 三、角色与权限

## 四、功能点拆解

## 五、规则说明

## 六、异常场景

## 七、风险分析

## 八、测试范围建议
```

### 15.2 Markdown 测试用例

固定列：

```markdown
| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
| xxx | P0 | xxx | 1. xxx<br>2. xxx | 1. xxx<br>2. xxx |
```

### 15.3 YAML 结构化用例

```yaml
test_cases:
  - title: ""
    priority: "P0"
    preconditions:
      - ""
    steps:
      - ""
    expected_results:
      - ""
    tags:
      - ""
    source_requirement: ""
```

### 15.4 JSON 结构化用例

```json
{
  "test_cases": [
    {
      "title": "",
      "priority": "P0",
      "preconditions": [],
      "steps": [],
      "expected_results": [],
      "tags": [],
      "source_requirement": ""
    }
  ]
}
```

---

## 16. 敏感数据隔离

### 16.1 不允许提交到 GitHub

```text
.env
.env.*
logs/
outputs/
data/
vector_store/
cache/
configs/local.yaml
configs/private.yaml
*.db
*.sqlite
*.log
```

### 16.2 `.gitignore` 建议

```gitignore
# env
.env
.env.*
!.env.example

# local config
configs/local.yaml
configs/private.yaml

# outputs
outputs/
logs/
data/
cache/

# vector db
vector_store/
*.faiss
*.index
*.db
*.sqlite

# python
__pycache__/
*.pyc
.venv/
venv/

# IDE
.idea/
.vscode/

# system
.DS_Store
Thumbs.db
```

---

## 17. 配置设计

### 17.1 `.env.example`

```env
FEISHU_APP_ID=
FEISHU_APP_SECRET=

DEFAULT_LLM_PROVIDER=deepseek

DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=

CLAUDE_API_KEY=

OPENAI_COMPATIBLE_API_KEY=
OPENAI_COMPATIBLE_BASE_URL=
```

### 17.2 `configs/config.example.yaml`

```yaml
app:
  name: ai-agentic-qa
  env: dev

input:
  support_feishu_doc: true
  support_markdown: true

workflow:
  enable_human_checkpoint: true
  default_checkpoint_node: requirement_analysis

rag:
  enabled: true
  top_k: 5
  vector_store: faiss

output:
  markdown: true
  yaml: true
  json: true
```

---

## 18. 开发阶段规划

### Phase 0：项目骨架

目标：

- 初始化 GitHub 仓库
- 建立项目目录
- 配置 `.gitignore`
- 配置 `.env.example`
- 配置基础 README
- 配置 pyproject.toml

交付物：

```text
可公开的项目骨架
```

---

### Phase 1：最小闭环

目标：

```text
Markdown 输入
↓
LLM 需求摘要
↓
输出 Markdown
```

交付物：

- CLI 可运行
- LLM Provider 抽象可用
- Markdown 输入可用
- Markdown 输出可用

---

### Phase 2：接入飞书文档

目标：

```text
飞书文档链接
↓
读取文档内容
↓
进入分析流程
```

交付物：

- 飞书 API Client
- 飞书 Doc Loader
- 飞书文档内容清洗

---

### Phase 3：LangGraph 工作流

目标：

```text
文档解析
↓
意图识别
↓
需求分析
↓
风险分析
↓
测试点生成
↓
用例生成
```

交付物：

- AgentState
- LangGraph Graph
- Workflow Runner
- 基础节点可运行

---

### Phase 4：RAG 接入

目标：

```text
知识库 Markdown
↓
Embedding
↓
Vector Store
↓
TopK 召回
↓
增强 Prompt
```

交付物：

- Markdown Loader
- Chunk Splitter
- Retriever
- FAISS / Chroma
- RAG Context 注入

---

### Phase 5：Agent / Skill 拆分

目标：

- IntentAgent
- RequirementAgent
- RiskAgent
- TestPointAgent
- TestCaseAgent
- ReviewAgent

交付物：

- Agent 职责清晰
- Skill 可复用
- Prompt 可版本化

---

### Phase 6：输出增强

目标：

- Markdown 报告
- Markdown 测试用例表格
- YAML 结构化数据
- JSON 结构化数据
- Mermaid 测试点脑图

交付物：

- 人类可评审文件
- Agent 可继续处理文件

---

## 19. 第一版最终验收标准

第一版完成后，应支持以下流程：

```text
在 PyCharm 中运行命令
↓
输入飞书需求文档链接或 Markdown 文件路径
↓
系统读取需求
↓
自动识别意图
↓
RAG 召回测试规范
↓
生成需求分析
↓
人工确认需求理解
↓
生成风险分析
↓
生成测试点
↓
生成测试用例
↓
输出 Markdown / YAML / JSON
```

验收产物：

```text
outputs/
├── requirement_analysis.md
├── risk_analysis.md
├── test_points.md
├── test_cases.md
├── test_cases.yaml
└── test_cases.json
```

---

## 20. 当前推荐优先级

最高优先级：

1. 项目骨架
2. LLM Provider 抽象
3. AgentState
4. Markdown 输入输出
5. LangGraph 最小流程
6. 飞书文档读取
7. RAG
8. Agent 拆分
9. 用例输出优化

暂缓：

1. 飞书 Bot
2. Web 页面
3. XMind
4. 多模型自动路由
5. GraphRAG
6. 复杂长期记忆
7. 自动执行测试用例

---

## 21. 总结

第一版不要追求“大而全”。

核心目标是先打通：

```text
输入需求
↓
理解需求
↓
召回知识
↓
生成分析
↓
生成用例
↓
结构化输出
```

项目的核心不是某个 Agent，而是：

```text
可控工作流 + 标准状态结构 + 可复用 Prompt/Skill + 可替换模型 + 可沉淀知识库
```

只要第一版把这个骨架搭好，后续接飞书 Bot、XMind、自动化脚本生成、日志分析、代码 Diff 分析都会比较顺。
