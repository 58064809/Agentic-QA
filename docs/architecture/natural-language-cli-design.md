# 纯自然语言 CLI 入口设计

## 背景

Agentic-QA 原 CLI 入口使用 argparse 子命令结构：

```bash
python -m runtime.cli run "帮我生成测试用例" --prd prd/sample-login-requirement
python -m runtime.cli analyze "帮我分析需求" --prd prd/sample-login-requirement
python -m runtime.cli mvp "..." --prd prd/sample-login-requirement [--confirm] [--use-llm]
```

这种设计要求用户记住子命令和参数，不符合「纯自然语言」的交互愿景。

## 设计目标

1. **单入口纯自然语言**：`agentic-qa "你的自然语言命令"`，无子命令、无参数
2. **LLM 语义路由**：从自然语言提取意图和文档来源，不依赖关键词硬匹配
3. **持久对话**：内置对话循环 + session 持久化，支持多轮连续交互
4. **自动写入**：默认写入产物（用户已确认 A 模式）

## 架构

```
用户输入 "帮我分析登录需求 D:\需求\登录.md"
         │
         ▼
┌─────────────────────┐
│  LLM Intent Router   │  读取 DEEPSEEK_API_KEY 环境变量
│                      │  输出: { intent, prd_path, url, summary }
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  PRD 工作区管理器    │  源文件 → prd/<name>/ 工作区
│                      │  prd/<name>/ 路径 → 直接复用
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Session 管理器      │  .runtime/sessions/default/
│                      │  持久化 thread_id、历史、last_prd_path
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  LangGraph 工作流    │  复用现有 mvp_graph 流程
│                      │  需求分析 / 测试用例 / MVP
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  对话循环 REPL       │  > 再补充边界用例
│                      │  > 退出
└─────────────────────┘
```

## 关键设计决策

### 1. 不引入 argparse

原设计使用 `argparse` + 子命令。新设计直接用 `sys.argv[1:]` 拼接成自然语言字符串。简化实现，减少维护成本。

### 2. LLM 路由是硬依赖

- 必须设置 `DEEPSEEK_API_KEY` 环境变量
- 无 API Key 时直接报错退出，不降级
- 使用 `.env` 文件 + `python-dotenv` 加载（或手动设置环境变量）

### 3. Session 命名固定为 `default`

- 用户不管理 session 命名
- 一个 terminal 对应一个 session
- 调用 `agentic-qa "重新开始"` 重置会话

### 4. PRD 工作区自动创建

```
D:\需求\登录.md → prd/登录/登录.md
                → prd/登录/metadata.yml
                → prd/登录/requirement.md (由 normalizer 转换)
```

### 5. 对话循环

- 首次执行后自动进入 REPL
- 输入 `退出` / `exit` / Ctrl+C 退出
- 输入 `重新开始` 重置当前会话

## 对话生命周期

```
首次:  agentic-qa "帮我分析登录需求 D:\需求\登录.md"
       执行 → 打印 → 进入 REPL

对话:  > 再补充几个边界用例
       意图: testcase_generation
       复用 last_prd_path
       执行 → 打印 → 等待

切换:  > 帮我分析支付模块 D:\需求\支付.md
       意图: requirement_analysis
       新 prd_path → 创建新工作区
       执行 → 打印 → 等待

退出:  > 退出
       👋 再见
```

## 数据目录

```
.runtime/
  sessions/
    default/
      metadata.json       Session 元数据（last_prd_path, last_intent, 等）
      checkpoints.db      LangGraph SqliteSaver 检查点
      history.jsonl       对话历史
  runs/
    <run_id>/             运行记录（不变）
```

## 与现有架构的兼容性

- `runtime/graph/` 模块不变：MVP 图、状态、节点、质量门
- `runtime/llm/` 扩展现有模块：新增 `intent_router.py` 但不移除原始模块
- `runtime/session/` 新模块，与现有 `runtime/records/` 共存
- `pyproject.toml` 入口点不变：`agentic-qa = "runtime.cli:main"`
- 旧参数 `--prd`、`--use-llm`、`--confirm` 不再使用
