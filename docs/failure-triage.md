# Failure Triage

Failure Triage 是 API 执行之后的显式诊断链路。它读取已经提交且哈希一致的执行事实，在受控范围内
采集日志，先形成确定性分析，再让专用模型提出带引用的根因假设。整个过程不会重放 API 请求，也不会
修改原 execution 的 execution、test、cleanup 或 report 状态。

```text
failed / dispatched error case-dataset
  → collect：受限日志查询与落盘前脱敏
  → Log Evidence v1
  → analyze：确定性信号、fingerprint、timeline
  → 受限 failure_triager 模型
  → FailureTriage v2
  → report：failure_analysis + 可选 bug_draft Candidate
  → 现有 diff / Review Gate / deterministic promote
```

## 事实与推断边界

| 层 | 内容 | 性质 |
|---|---|---|
| Execution Evidence v2 | case/dataset、请求是否发送、失败事实、时间和 correlation context | API 执行审计事实 |
| Log Evidence v1 | 受限查询意图、Provider 结构 Hash、脱敏日志条目与内容 Hash | 日志事实 |
| Log Analysis v1 | 异常聚合、依赖信号、fingerprint、occurrence 与 `LOG-*` timeline | 确定性派生事实 |
| FailureTriage v2 | 分类、服务、异常、置信度、`EXEC-*`/`LOG-*` 引用与建议 | 模型假设；不是已确认根因 |
| Bug Draft v1 | 通过 Bug Gate 的待审核缺陷草稿 | Candidate；不是外部缺陷或发布事实 |

新执行使用 Execution Evidence v2。历史 v1 只经兼容投影用于报告与分诊，缺少的请求发送信息会以
诊断表达，不会被猜测。Failure Triage v1 同样仅作历史只读兼容；新分析写 v2。

## Correlation 解析

响应头名称按大小写无关处理。`traceparent` 优先提供 W3C trace/span ID；缺少合法 traceparent 时
`x-trace-id` 可提供 trace ID。Request ID 的顺序为 `x-request-id`、`request-id`。内置
`x-correlation-id`、`x-tid`、`tid` 进入 custom IDs；额外响应头需要在目标 API 环境的
`correlation_response_headers` allowlist 中声明。

非法 traceparent、冲突值或非法 ID 只形成无原值 diagnostic，不改变原 API 结果。认证、Cookie、
Token、密码和 Secret 类头名不会进入 correlation context。

## 日志 Provider 边界

`failure collect` 不随 `api run` 自动发生。查询身份来自 immutable execution plan，范围来自根配置
`logs`：environment、API service、允许的下游 service、时间窗、条数与响应字节预算都是确定值。
production-like 环境会在读取日志前被拒绝。

LocalFile Provider 只读取仓库 `local-logs/` 下配置命中的普通非链接文件，支持 JSONL 和受限文本日志。
无时间戳的文本只在 correlation 精确匹配时纳入。Loki Provider 只接受确定性 builder 生成的 LogQL，
并执行 HTTPS trusted origin、关闭重定向、超时和响应预算校验；模型与用户都不提供原始 LogQL。

原始 Provider 响应只在内存中短暂存在。Authorization、JWT、Cookie、密码、API Key、access/refresh
token、手机号、邮箱、证件与银行卡在任何 collection 文件写入前脱敏；用于关联的安全 ID 保留。

## 分析与集合选择

每个失败 case/dataset 对应独立 collection。相同输入 Hash 会复用原 collection，产物保持 create-only。
同一 case/dataset 出现多个 collection 时，`failure analyze` 和 `failure report` 在缺少
`--collection-id` 时 fail closed，不使用 mtime 猜测“最新”结果。

确定性分析最多保存 300 个聚合信号。fingerprint 由 service、exception、规范化消息和顶部堆栈帧
计算，引用可以回到具体 `LOG-*` 或 `EXEC-*` 事实。

模型调用的输入只有脱敏执行失败事实、Log Analysis 和允许引用索引，工具列表为空。模型输出中的
引用、service 和 exception 会被确定性复验；失败时进行一次结构化修订。模型错误或两次校验仍失败
写入 `triage_status=failed`，CLI 返回 1；证据有效但不足以支持 probable 结论时写入
`insufficient_evidence`，CLI 返回 0。

## Bug Gate 与审核

`test-script`、`test-data`、`environment`、`unknown` 和 insufficient evidence 不产生 Bug Draft。
产品、依赖、数据库等分类需要有效事实引用和至少 probable 的置信度；contract 可以由明确的执行断言
或契约事实支撑。通过后也只创建 `failure_analysis` 和可选 `bug_draft` Candidate，后续仍走现有
`run diff`、人工 Review 与确定性 promote，不会自动创建 Jira、禅道或 GitHub Issue。

完整命令参数与退出码见 [CLI 参考](cli-reference.md)，目录与可变性见
[工作区与产物版本](artifact-versioning.md)。

## 评测边界

`python -m harness eval run` 的 Failure Triage 项是离线契约/安全 Golden，验证引用可解析、敏感信息
零泄露和高置信 unsupported claim 为零。`python -m harness eval failure-triage-live` 使用当前
`failure_triager` Prompt、当前 ModelGateway 路由和固定脱敏场景；它作为独立 Nightly Live Eval，
不会被离线预写 proposal 替代。
