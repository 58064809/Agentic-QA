# Agentic-QA 命令入口

`COMMANDS.md` 描述用户、Bot、CLI 和 Runtime 如何表达任务意图。它不是旧式子命令清单，也不是 Workflow 细节表；Workflow、Rules、Prompts 和 Skills 的执行契约分别放在对应目录中维护。

Agentic-QA 的主入口是自然语言。CLI 只是本地调试和脚本化入口之一，和 Chat、Bot、API 使用同一套语义：识别意图、定位 PRD 工作区、生成候选产物、等待 Review Gate、确认后发布正式产物。

## 总原则

- 用户用自然语言描述目标，不需要记住内部节点名。
- Runtime 负责识别意图、选择工作流、加载上下文和写入目标 PRD 工作区。
- 生成类任务默认只写候选产物：`prd/<id>/runs/<run_id>/artifact-preview.md`。
- 候选产物进入 `reviews/*.review.yml`，状态为 `needs_human_review`。
- 只有用户明确确认通过后，Runtime 才能 promote 到正式 `artifacts/`。
- CLI 的 `rag`、`resume`、`promote` 等子命令用于本地调试和最小闭环验证，不改变自然语言优先的设计。

入口模式：

- `natural language mode`：默认主入口，用户用自然语言描述 QA 目标、需求来源和审核反馈。
- `debug mode`：工程辅助入口，包括 `rag`、`resume`、`promote` 等显式子命令，用于本地调试、索引检查和最小闭环验证。

## 常用入口

自然语言执行任务：

```bash
python -m runtime.cli "分析 prd/demo-requirement 并生成测试用例"
```

自然语言确认并发布正式产物：

```bash
python -m runtime.cli "测试用例通过，发布正式产物 prd/demo-requirement"
```

恢复上次 interrupt Review Gate：

```bash
python -m runtime.cli resume run-20260616-060850-0ec07a "测试用例通过，发布正式产物"
```

显式发布指定 run 的候选产物：

```bash
python -m runtime.cli promote prd/demo-requirement run-20260616-060850-0ec07a testcases
```

调试 RAG：

```bash
python -m runtime.cli rag status
python -m runtime.cli rag build
python -m runtime.cli rag search "边界值 活动规则"
```

创建和校验 PRD 工作区：

```bash
python scripts/create_prd_workspace.py demo-requirement
python scripts/validate_prd_workspace.py prd/demo-requirement
```

## 自然语言任务

### 需求分析

示例：

```text
分析 prd/demo-requirement 的需求，识别业务规则、风险和待确认项。
```

Runtime 语义：

- 目标工作区：`prd/demo-requirement`
- 目标产物：需求分析候选内容
- 默认输出：`runs/<run_id>/artifact-preview.md`
- Review 状态：`reviews/requirement-analysis.review.yml = needs_human_review`
- 不直接覆盖：`artifacts/requirement-analysis.md`

### 测试用例生成

示例：

```text
基于 prd/demo-requirement 生成测试用例，覆盖主流程、异常、边界值和状态流转。
```

Runtime 语义：

- 目标工作区：`prd/demo-requirement`
- 目标产物：测试用例候选内容
- 默认输出：`runs/<run_id>/artifact-preview.md`
- Review 状态：`reviews/testcases.review.yml = needs_human_review`
- 不直接覆盖：`artifacts/testcases.md`

### 需求分析 + 测试用例

示例：

```text
分析 prd/demo-requirement 并生成测试用例。
```

Runtime 语义：

- 目标工作区：`prd/demo-requirement`
- 目标产物：需求分析候选内容、测试用例候选内容
- 默认输出：同一个 `runs/<run_id>/artifact-preview.md`
- Review 状态：需求分析和测试用例均进入 `needs_human_review`
- 不直接覆盖正式 `artifacts/`

### 确认通过并发布

示例：

```text
测试用例通过，发布正式产物 prd/demo-requirement。
```

```text
需求分析和测试用例都通过，发布正式产物 prd/demo-requirement。
```

Runtime 语义：

- 找到目标工作区。
- 从输入中识别 artifact；多产物场景未明确目标时进入 `clarify` 或二次确认。
- 从输入中识别 `run_id`；未明确时读取 `runs/latest.yml`。
- 先通过 Review Gate 将自然语言解析为 `ReviewDecision`。
- Review Gate 只能把目标 `reviews/*.review.yml` 从 `needs_human_review` 更新为 `approved`、`rejected` 或 `needs_changes`。
- 只有 `approved` 状态允许调用确定性 `promote_artifacts()`。
- 写入正式产物到 `artifacts/`。
- 归档旧版本到 `artifacts/history/`。
- 更新 `metadata.yml`、`reviews/*.review.yml` 和 history index。

安全约束：

- LLM 只能输出结构化 `ReviewDecision`，不能直接写正式产物。
- LLM 不能直接把状态改为 `confirmed`。
- 多产物场景必须明确目标 artifact；否则进入 `clarify` 或二次确认。
- “先不要发布”“不要发布”等否定表达不能直接 approve。
- 低置信度或非法 JSON 解析结果不能直接发布。

### 要求修改

示例：

```text
测试用例不通过，补充支付失败、库存不足和优惠券失效场景。
```

Runtime 语义：

- 不发布正式产物。
- 将 Review Gate 保持在待修订状态。
- 后续生成仍写入新的 `runs/<run_id>/artifact-preview.md`。
- 正式 `artifacts/` 只能在确认通过后更新。

## 本地调试子命令

### `resume`

用自然语言恢复 interrupt Review Gate：

```bash
python -m runtime.cli resume <run_id> "测试用例通过，发布正式产物"
```

参数：

- `run_id`：必填，目标 Runtime 运行记录。
- 第二个及后续参数：必填，用户原始自然语言审核意见。

行为：

- 将自然语言作为 `user_input` 传给 `resume_recorded_workflow()`。
- 继续由 `process_review_gate()` 判断 approve、reject、revise、hold、show_diff 或 clarify。
- `approved` 只表示候选产物通过 Review Gate，不直接写正式产物。
- 正式产物仍必须由独立 `promote` 或自然语言发布入口完成。

### `promote`

显式发布候选产物：

```bash
python -m runtime.cli promote prd/<requirement> [run_id] [artifact]
```

参数：

- `prd/<requirement>`：必填，目标 PRD 工作区。
- `run_id`：可选。缺省时读取 `prd/<requirement>/runs/latest.yml`。
- `artifact`：可选。支持 `testcases`、`requirement_analysis`。缺省时按需求分析 + 测试用例处理。
- 除 PRD 路径外，Runtime 会从剩余参数文本中识别 `run_id` 和 `artifact`。参数顺序不强制，但推荐按 `[run_id] [artifact]` 编写，便于人工阅读和排查。

示例：

```bash
python -m runtime.cli promote prd/demo-requirement testcases
python -m runtime.cli promote prd/demo-requirement run-20260616-060850-0ec07a testcases
python -m runtime.cli promote prd/demo-requirement run-20260616-060850-0ec07a requirement_analysis
```

说明：

- 第一条未显式指定 `run_id`，Runtime 会读取 `prd/demo-requirement/runs/latest.yml`，并只发布测试用例。
- 第二条显式指定 `run_id`，并只发布测试用例。
- 第三条显式指定 `run_id`，并只发布需求分析。

行为：

- 通过确定性 Review Gate 把目标 review 更新为 `approved`。
- 再调用正式发布逻辑。
- 成功后输出正式 artifact 路径。
- 如果找不到 preview 或 review 未满足条件，命令失败并说明原因。

### `rag`

RAG 调试入口：

```bash
python -m runtime.cli rag status
python -m runtime.cli rag build
python -m runtime.cli rag search "查询内容"
```

行为：

- `status`：查看索引状态和配置。
- `build`：强制重建索引。
- `search`：按当前配置检索上下文并输出 trace。

这些命令只用于调试 RAG，不生成 QA 产物。

## 工作区产物流转

当前标准流转：

```text
自然语言任务
  -> Runtime 识别意图
  -> 加载 PRD 工作区和上下文
  -> RAG 检索
  -> QA Agent 生成内容
  -> 质量检查
  -> human_review_node interrupt
  -> run_status = interrupted
  -> 用户自然语言 resume
  -> reviews/*.review.yml = approved
  -> artifact_preview_writer_node
  -> runs/<run_id>/artifact-preview.md
  -> 用户执行 promote
  -> artifacts/<artifact>.md
  -> artifacts/history/<artifact>/index.yml
```

约束：

- `runs/<run_id>/artifact-preview.md` 是候选产物。
- `artifacts/<artifact>.md` 是正式产物。
- `reviews/*.review.yml` 是 Review Gate 的结构化记录。
- `metadata.yml` 记录当前版本、最新 run、preview 路径和 artifact 状态。
- 未确认的候选产物不得进入正式 `artifacts/`。

## 意图识别优先级

Runtime 处理用户输入时按以下顺序解释：

1. 显式本地调试子命令，例如 `rag`、`resume`、`promote`。
2. 自然语言确认发布，例如“通过，发布正式产物”。
3. 自然语言生成任务，例如“分析需求”“生成测试用例”。
4. 会话上下文复用，例如继续使用上一次 PRD 工作区。
5. 无法识别时提示用户补充 PRD 路径或需求来源。

## 推荐表达

生成候选产物：

```text
分析 prd/demo-requirement 并生成测试用例。
```

只生成测试用例：

```text
为 prd/demo-requirement 生成测试用例，重点覆盖边界值和异常流程。
```

确认发布测试用例：

```text
测试用例通过，发布正式产物 prd/demo-requirement。
```

指定 run 发布：

```text
run-20260616-060850-0ec07a 的测试用例通过，发布正式产物 prd/demo-requirement。
```

要求修订：

```text
测试用例不通过，补充优惠券过期、库存不足和重复提交场景。
```

查看 RAG：

```text
先用 rag search 看一下活动规则相关上下文。
```

## 不推荐表达

不要要求 Runtime 直接覆盖正式产物：

```text
直接重写 artifacts/testcases.md
```

不要把生成完成当成审核通过：

```text
生成出来就算通过
```

不要跳过 Review Gate：

```text
不用确认，直接发布
```

如果用户确实需要发布，必须表达“通过”“确认”“发布正式产物”等明确确认语义。

## Chat 回执要求

任务完成后的 Chat 回复遵守 `rules/agent-output-rules.md`：

- 变更摘要
- 修改文件
- 验收结果
- 待人工确认
- 下一步建议

Chat 中不粘贴完整大文件，不用完整 diff 代替文件路径和验收结果。
