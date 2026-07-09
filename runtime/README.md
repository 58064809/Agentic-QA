# Runtime 架构文档

## 概述

Runtime 是 Agentic-QA 的轻量执行引擎，提供**纯自然语言入口**、**LLM 语义路由**、**session 对话循环**和**自动持久化**能力。用户无需记忆子命令或参数，只需输入自然语言，Runtime 即可自动识别意图、路由到对应工作流、维护对话上下文并自动写入产物。

---

## 一、入口：自然语言指令

### 入口形式

用户指令本体是纯自然语言；`agentic-qa` 只是在终端中启动 Runtime 的可执行名，不属于用户意图文本。

示例：

```text
帮我分析 prd/sample-login-requirement 的需求
基于 prd/sample-login-requirement 生成测试用例
分析需求并生成测试用例
继续上一轮分析，补充边界条件
```

终端中可通过启动器传入同样的自然语言：

```bash
agentic-qa 帮我分析 prd/sample-login-requirement 的需求
agentic-qa 基于 prd/sample-login-requirement 生成测试用例
agentic-qa 分析需求并生成测试用例
agentic-qa 继续上一轮分析，补充边界条件
```

### 设计原则

- **纯自然语言**：用户意图文本不接受 `--flags`、`--options`、子命令或结构化参数。所有指令信息（目标 PRD、操作类型、约束条件）均从自然语言中由 LLM 语义解析提取。
- **无子命令无参数**：废除 `analyze`、`generate-testcases`、`mvp`、`run`、`confirm` 等子命令体系。废除 `--prd`、`--confirm`、`--use-llm`、`--no-record-run` 等参数。所有配置（PRD 路径、写入确认、LLM 开关等）均由 LLM 从对话上下文和历史记录中推断，或在首次使用时由对话引导用户明确。
- **单一 Runtime 入口**：终端通过 `agentic-qa` 启动器进入；AI 编程助手或 IDE Chat 直接把自然语言传给 Runtime。两者后续都走同一套路由、RAG、LangGraph 和记录逻辑。

### 入口工作流

```
用户输入自然语言
    │
    ▼
Runtime 接收原始自然语言文本
    │
    ▼
LLM 语义路由解析（见第二节）
    │
    ▼
路由到对应 Workflow / Task
    │
    ▼
执行完成后自动写入产物
    │
    ▼
回复用户摘要（含路径、验收结果、待确认项）
```

---

## 二、LLM 语义路由

### 路由模型

Runtime 默认使用 LLM 对用户自然语言指令进行语义路由，不再依赖子命令。LLM 不可用、调用失败或返回不可解析结果时，降级到确定性路由兜底，仍尽量识别 PRD 路径和意图。

### 路由输入

```
- 用户原始自然语言指令
- 当前 session 上下文（最近 N 轮对话摘要）
- 可用 Workflow 清单（来自 workflows/）
- 当前 PRD 工作区状态（可选）
```

### 路由输出

```json
{
  "intent": "analyze | generate-testcases | full-pipeline | revise | export | continue | ...",
  "target_prd": "sample-login-requirement",
  "confidence": 0.95,
  "requires_confirmation": false,
  "extracted_params": {
    "scope": "full",
    "constraints": ["边界条件", "异常场景"]
  }
}
```

### 路由策略

| 场景 | 路由行为 |
|------|---------|
| 明确意图 | 直接路由，无需确认 |
| 模糊意图 | 回复澄清问题，引导用户明确 |
| 多意图 | 拆分为子任务顺序执行 |
| 继续/补充 | 识别为上轮 session 延续，加载历史 checkpoint |

### 可用意图

- `analyze` — 需求分析
- `generate-testcases` — 测试用例生成
- `full-pipeline` — 分析+用例全链路
- `revise` — 按评审意见增量修订
- `export` — 导出中文评审文件
- `continue` — 继续上轮未完成任务
- `status` — 查询运行状态或历史
- `help` — 引导用户了解可用能力

---

## 三、Session 对话循环

### 会话生命周期

```
Session 开始（首次 agentic-qa 调用）
    │
    ▼
用户输入 → LLM 语义路由 → 执行 Workflow → 输出摘要
    │                                            │
    └──────── 继续输入 ←─────────────────────────┘
    │
    ▼
Session 结束（显式结束 / 超时 / 所有任务完成）
```

### Session 状态

每个 session 包含：

```yaml
session_id: uuid
created_at: timestamp
last_active: timestamp
thread_id: string  # LangGraph thread_id
history:
  - turn: 1
    user_input: "..."
    intent: "analyze"
    target_prd: "..."
    result: "success"
    artifacts: ["prd/.../runs/<run_id>/artifact-preview.md"]
  - turn: 2
    user_input: "继续..."
    ...
store_namespace: ("agentic-qa", "sessions", "<session_id>")
status: "active | completed | expired"
```

### 对话上下文维护

- 每轮对话自动追加到 session 历史
- LLM 路由时携带最近 5 轮对话摘要（可配置）
- 支持跨轮引用：用户说「继续上一轮」「补充边界条件」时，路由自动加载上轮 checkpoint
- 同一 session 内，PRD 路径、风格偏好等上下文自动继承

### 自动写入（不打断）

- **不暂停等待用户确认**：Workflow 执行完成后自动写入产物，不在执行中途暂停等待 `approve`/`reject` 命令。
- **写入后通知**：写入完成后，回复中告知用户已写入的路径和内容摘要。
- **覆盖保护**：如果目标产物已存在，自动检查差异；仅在不一致时询问用户是否覆盖（异步轻量询问，不阻塞后续任务）。
- **错误处理**：写入失败时自动重试一次，仍失败则在回复中给出错误信息和手动操作建议。

---

## 四、持久化

### Store 与 Checkpointer 分工

Runtime 区分 LangGraph 的两类持久化能力：

- **Store**：跨 thread 的长期数据，当前用于 session 元数据和对话历史。
- **Checkpointer**：单个 thread 的图状态，用于中断恢复、失败恢复、human-in-the-loop 和 time travel。

`runtime/session/store.py` 使用 LangGraph `BaseStore` 接口保存 session 数据：

| 数据 | LangGraph Store namespace | key | 用途 |
|------|---------------------------|-----|------|
| Session 元数据 | `("agentic-qa", "sessions", "<id>", "metadata")` | `metadata` | thread_id、最近 PRD、最近意图、历史计数 |
| 对话历史 | `("agentic-qa", "sessions", "<id>", "history")` | `<sequence>-<uuid>` | 每轮对话输入/输出 |

本地未配置 Store DSN 时使用 `InMemoryStore`，适合单进程调试和单元测试。需要跨进程长期保存 session 时，设置：

```powershell
$env:AGENTIC_QA_STORE_POSTGRES_DSN="postgresql://postgres:<password>@localhost:5432/postgres?sslmode=disable"
```

该连接串只从环境变量读取，不写入仓库。

### 运行记录持久化

保持与 MVP 阶段兼容的运行记录结构，每次 Runtime 执行自动记录：

```text
.runtime/runs/<run_id>/run-summary.json
.runtime/runs/<run_id>/run-summary.md
.runtime/runs/<run_id>/run-state.json
.runtime/runs/<run_id>/checkpoint-manifest.json
```

运行记录包含：意图、目标 PRD、LLM 调用次数、执行状态、产物路径、错误摘要。不记录密钥或敏感信息。

### 自动恢复

- 如果 session 因异常中断（进程退出、网络中断），下次相同 session_id 的调用自动加载最新 checkpoint 恢复。
- 没有显式 session_id 时，按以下优先级匹配：
  1. 最近 30 分钟内活跃的同一用户 session
  2. 同一 PRD 的最近 session
  3. 创建新 session

### 不提交到 Git

整个 `.runtime/` 目录被 `.gitignore` 排除。所有持久化数据仅限本地开发环境和运行时使用。

---

## 五、架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                       用户自然语言输入                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     Runtime 自然语言入口                       │
│  (终端由 agentic-qa 启动；Chat 直接传入自然语言)                │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    LLM 语义路由                               │
│  意图识别 → 参数提取 → PRD 定位 → 路由决策                   │
└──────────┬──────────────────────────────────────┬───────────┘
           │                                      │
           ▼                                      ▼
┌──────────────────────┐    ┌──────────────────────────────┐
│   Workflow 执行       │    │    Session 管理               │
│  ┌────────────────┐   │    │  ┌─────────────────────────┐ │
│  │ 需求分析        │   │    │  │ 对话历史                │ │
│  │ 测试用例生成    │   │    │  │ 上下文快照              │ │
│  │ 全链路          │   │    │  │ Checkpoint 恢复         │ │
│  │ 增量修订        │   │    │  │ 自动续接                │ │
│  └────────┬───────┘   │    │  └─────────────────────────┘ │
└───────────┼───────────┘    └──────────────────────────────┘
            │                             │
            ▼                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    自动写入产物                               │
│  (不打断，写入后通知，覆盖保护)                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 六、与现有资产的交互

| 资产 | 交互方式 |
|------|---------|
| `AGENTS.md` | Runtime 读取 Agent 角色定义，不修改 |
| `COMMANDS.md` | Runtime 不依赖 COMMANDS.md 路由，仅用于信息参考 |
| `workflows/` | Runtime 按路由结果调用对应 Workflow |
| `rules/` | Runtime 遵守质量门、路径、命名规则 |
| `skills/` | Runtime 读取 Skill 定义作为 LLM 上下文 |
| `knowledge/` | Runtime 读取 Knowledge 作为 LLM 上下文 |
| `prd/<id>/` | Runtime 写入 analysis/ 和 testcases/ 产物 |
| `prompts/` | Runtime 读取 Prompt 模板作为 LLM 上下文 |

---

## 七、对比 MVP 阶段变更

| 维度 | MVP 阶段 | 新架构 |
|------|---------|--------|
| 入口 | `python -m runtime.cli <子命令>` | `agentic-qa <自然语言>` |
| 参数 | `--prd`, `--confirm`, `--use-llm` 等 | 无参数，LLM 语义提取 |
| 路由 | 子命令映射 | LLM 语义路由 |
| 对话 | 单次执行 | 多轮 session 对话循环 |
| 写入 | 需 `--confirm` 或 `confirm` 命令 | 自动写入（不打断） |
| 暂停 | `approve`/`reject`/`resume` 暂停等待 | 无需暂停，写入后通知 |
| 会话 | 无 session 概念 | 完整 session 生命周期管理 |
| 持久化 | 仅运行记录 | session + 运行记录双持久化 |
| 覆盖保护 | 拒绝覆盖 | 差异检查 + 轻量询问 |

---

## 八、后续演进方向

1. **多用户 session 隔离**：支持多用户并行 session，通过用户标识自动隔离
2. **Session 超时与清理**：超过 N 天未活跃的 session 自动归档
3. **对话历史检索**：支持按关键词/PRD/时间范围检索历史对话
4. **异步通知**：长时间运行的任务完成后推送通知
5. **Web Dashboard**：可视化查看 session、运行记录和产物状态
6. **Session 导出**：将完整对话历史和产物导出为可分享文档

## LangSmith Observability

Runtime 的 LangGraph trace、debug、状态转移可视化、evaluate 和 runtime metrics 交给 LangSmith。启用 `observability.provider=langsmith` 与 `observability.enabled=true`，并设置 `LANGSMITH_API_KEY` 后，Runner 会在 LangGraph config 中附加 `run_name`、`tags` 和 `metadata`。

本地 `.runtime/runs/<run_id>/` 不保存节点事件流，只保留 run summary、run state、graph state、review events、RAG trace 和 checkpoint manifest。
