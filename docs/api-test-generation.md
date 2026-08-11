# API 测试契约

当测试目标包含 API 时，`api_test_draft` 提供可审核、可发布和可执行的机器用例。Candidate 与
published 文件均为 YAML，数据契约是 `agentic-qa.api-cases.v1.2`。

## 场景

| 来源 | endpoint 事实 | 可生成内容 | 系统标记 |
|---|---|---|---|
| SourceBundle 中完整且成功解析的 OpenAPI 3.x/Swagger 2.0 | confirmed | method/path、参数、请求体、响应、安全定义和契约断言 | high-confidence source ref |
| 残缺或解析失败的 OpenAPI | partial/missing | 缺口与待确认草案 | 解析问题 |
| Markdown/PRD | 不构成协议事实 | 业务场景、规则候选 | 待确认 endpoint |
| [API Discovery 抓包](api-discovery.md) / 示例请求 | 作为观察样本 | 候选接口与复现线索 | observed / 非完整契约 |

## 操作与系统响应

启动 run 时选择 `api_test_draft`。系统先冻结 `sources/`，再由 `openapi.inspect` 归一化契约。
模型返回强类型 `AgentOutput.api_test_cases`，Harness 校验业务规则引用、endpoint 与 OpenAPI
证据，并稳定渲染为 `candidates/<run_id>/api_test_draft/raw.yml`。

无完整契约时，系统仍可生成 `missing`、`pending_confirmation` 或 `partial` 用例；这些用例的
method/path 为 `null`。模型直接声称一个未出现在本次 OpenAPI 检查结果中的 confirmed
endpoint 时，artifact validation 返回错误并进入修订循环。

Candidate 停在人工 Review Gate。人工选择通过质量门的版本后，发布文件位于：

```text
workspaces/<workspace>/published/api_test_draft/current.yml
```

`api.execute` 读取这份 published YAML，并继续受 ExecutionProfile、workspace policy、环境变量和
HTTP method allowlist 控制。请求位于 `request.method/path`，断言位于类型化 `assertions`。
workspace 环境可以选择静态 token 或执行前登录取 token；认证头由执行器统一注入，不改变
API Cases v1.2 文件。

## 场景变量、数据集与 cleanup

`variables` 和 `cleanup` 保持 API Cases 的既有字段位置。Candidate 生成校验、通用质量门和
执行前预检共同拒绝未知字段、非法路径、前向变量引用或错误 cleanup；历史 published 文件定义无效
时记录 `blocked`，不发送该用例请求。

每个业务请求和 cleanup 请求都会在发送前解析其 `${ENV_NAME}` 引用；任一值缺失时，该请求记录为
`blocked`。请求路径、Header 名称与换行、传输层 Header，以及认证/密钥类字段也使用与登录请求相同
的安全校验。敏感字段值使用环境变量或已声明的运行时变量引用。

运行时变量使用 `${{name}}`，与环境变量 `${ENV_NAME}` 区分。完整占位符保留数字、布尔、对象或
数组类型；嵌入字符串时只接受标量。响应提取值仅在本次执行进程内保存，不写回 YAML 或 Evidence。

OpenAPI Path Parameter 不新增字段，而是放在现有 `request.path` 中。契约 `/orders/{id}` 对应
`/orders/${{order_id}}`：首版只接受占满整个路径段的 `{name}` 与 `${{name}}`，不接受
`/files/{id}.json` 这类嵌入式模板。变量来源限定为当前 dataset 或更早用例声明的提取值，并满足该
Path Parameter 的 required、type、enum、pattern 和范围约束。静态段不一致、缺失或额外动态段，
以及同时匹配多个 operation 的情况都会让 Candidate 进入修订。cleanup 继承所属主用例的 OpenAPI
来源并遵循同一匹配规则。

Candidate 校验、通用质量门和 API Golden 会把每个 dataset 分别展开到 path、query、headers 与
body，再验证 operation、参数和 JSON request body Schema。完整占位符保留原生 JSON 类型；字符串
内插仅接受标量。校验覆盖 required、enum、数值与长度范围、pattern、数组约束、组合 Schema 和
`additionalProperties`。OpenAPI 默认允许额外对象属性；`additionalProperties: false` 关闭
额外属性接收。若值来自上游 response extraction，生成期只验证变量来源、提取字段
和静态结构，未知叶子值的类型延迟到执行期，不会用虚构示例代替。

```yaml
variables:
  datasets:
    - id: one-item
      values: {sku: SKU-001, quantity: 1}
    - id: two-items
      values: {sku: SKU-002, quantity: 2}
  extract:
    order_id:
      source: response_json
      path: $.data.id
      required: true
cleanup:
  - id: delete-order
    title: 删除本次创建的订单
    request:
      method: DELETE
      path: /orders/${{order_id}}
      headers: {}
      query: {}
      body: {}
    assertions:
      - type: status_code
        expected: [204]
```

| 能力 | 规则 |
|---|---|
| `datasets` | 系统校验同一用例的数据集 ID 唯一且变量名集合相同；每个数据集独立展开并通过 OpenAPI Schema 校验，执行时产生独立 Evidence case |
| `response_json` | 使用同一受限 JSON 路径语法提取 |
| `response_header` | 头名大小写不敏感；拒绝 Cookie、Token 等敏感头名 |
| 跨用例变量 | 系统校验引用来自更早用例声明的提取变量；上游未产生所需值时下游为 `blocked` |
| cleanup | 主请求发出后登记，全部业务用例结束后逆序执行；每一步形成独立 Evidence case |

提取变量仅在生产者状态为 `passed` 时进入共享作用域。失败、错误或 blocked 的生产者不会向下游发布
变量；已发出主请求的 cleanup 仍保留该次迭代的局部变量快照。数据集值、共享变量和 cleanup 局部值
均进入错误信息脱敏作用域。跨用例变量重名、数据集遮蔽已有变量，以及占用 `::` Evidence ID 分隔符
的用例 ID 会在 Candidate 校验阶段返回修订意见。

一个带多个 datasets 的生产者会按顺序覆盖同名共享提取值，因此后续用例读取最后一次提取结果；每次
迭代的 cleanup 会保留自己的变量快照。需要一一对应的完整业务链时，应生成多个显式场景用例。

## 执行与 pytest 导出

直接执行已发布用例：

```powershell
python -m harness api execute demo run-api-001 `
  --environment qa `
  --allow-http-method GET `
  --allow-http-method POST `
  --allow-http-method DELETE
```

确定性导出 pytest adapter：

```powershell
python -m harness api export-pytest demo
```

导出的 `workspaces/demo/exports/api_test_draft/test_api_cases.py` 不复制或重新生成测试逻辑，而是调用
公开 Harness API 执行 published YAML。文件绑定源 SHA-256；published 发生变化后，旧 adapter 返回
hash 不匹配，重新导出会生成与新版本绑定的文件。
adapter 在导出时绑定已审核环境，运行时由 Harness 重新读取根目录 `agentic-qa.local.yml`。无需设置
API Base URL、环境、方法或认证环境变量。导出不批准 Candidate，也不改变 published。

adapter 对每个业务用例、dataset 实例和 cleanup Evidence ID 生成独立 pytest item；底层场景在 session
内只执行一次。这样流水线可以精确显示失败项，同时仍保持跨用例变量链和逆序 cleanup 语义。

## 支持的断言

`assertions` 保持 `type`、`expected`、`path` 三字段结构。Candidate 生成与质量门会校验断言定义；
未知类型或错误参数进入修订，历史 published 用例中的无效断言在发送认证或业务请求前记录为
`blocked`。

| `type` | 参数 | 判断 |
|---|---|---|
| `status_code` | `expected` 为状态码或非空状态码列表 | 实际状态码属于期望集合 |
| `json_field_exists` | `path` | JSON 路径存在 |
| `json_field_equals` | `path`、显式 `expected` | JSON 值按严格类型深度等于期望值 |
| `json_field_contains` | `path`、显式 `expected` | 对象递归包含子集、数组包含严格类型的期望成员、字符串包含子串 |
| `header_equals` | `path` 为非敏感响应头名、`expected` 为字符串 | 头名称不区分大小写，值精确相等 |
| `response_time_ms_max` | `expected` 为 1–60000 的整数 | 收到响应前的请求耗时不超过上限 |

JSON 路径支持根 `$`、对象字段 `.field` 和数组索引 `[index]`，例如
`$.data.items[0].id`；通配符、过滤器和负数索引会被拒绝。值型 JSON 断言与响应头断言的执行证据
只保存存在性、值类型和规范化 SHA-256，不保存原始响应值。
严格类型比较会区分 JSON 布尔值、整数和浮点数，例如 `true`、`1` 与 `1.0` 不互相等价。

系统拒绝指向 Token、Cookie、密码、API Key 等敏感字段的断言路径，以及在 `expected` 对象键或字符串中
出现的疑似敏感值。合法的值型断言会把 expected 与实际值都摘要化写入 Evidence，因此不会复述业务字符串或
响应头原值。

## URL 与 cleanup 执行边界

根配置以 operation 而不是 HTTP 方法猜测副作用：未声明时 GET 默认为 `read_only`，
POST/PUT/PATCH/DELETE 默认为 `mutation_cleanup`；精确 policy 可改为 `mutation_idempotent` 或
`mutation_manual`。后者由人工执行，预检不会进入 transport。`mutation_idempotent` 要求声明服务端
实际支持的 Header，Harness 生成 execution/case/operation 绑定的确定性值，但不会自动重试 mutation。
命名空间隔离同样由已审核策略精确声明 Header/query/body 注入位置，原值不写入报告。

confirmed 的 `POST`、`PUT`、`PATCH`、`DELETE` 默认视为状态变更；缺少带断言 cleanup 的 Candidate 会被质量门拒绝。确实无需自动 cleanup 的
operation 需要在根配置环境下以规范化 `METHOD /path-template` 声明为 `mutation_no_cleanup`；它仍是 mutation、仍记录 intent，且不会自动重试。项目级登录
不进入 API Cases，因此自动豁免。状态变更请求进入 transport 前，cleanup 会先以 `armed` 写入
AES-256-GCM 加密 journal，其中保留 case、cleanup、路径模板、已知局部变量与
`mutation_may_happen=true`。响应和提取结果返回后，可完整解析的 cleanup 从 `armed` 转为 `pending`，
再按 LIFO 执行。

进程在请求发送阶段退出时，`armed` 会保留为 `cleanup_indeterminate`，报告要求人工扫描环境；它不会进入
自动恢复队列。`api cleanup resume` 仅恢复从未发送的 `pending` cleanup，不重放 `armed`、`running`、
`failed` 或业务请求。契约允许客户端预生成稳定 ID 时，场景优先使用该 ID，减少响应提取前的不确定窗口。
正常 cleanup 按 LIFO 执行，设计原则与
[pytest safe teardowns](https://docs.pytest.org/en/stable/how-to/fixtures.html#safe-teardowns)
一致；恢复仍由 Harness 的加密 journal 和防重放状态决定，而不是 pytest retry。

`api.execute` 只接受不含用户信息、查询和片段的 HTTP(S) base URL。执行器将业务请求与登录请求的最终 URL
约束在配置的 Origin 和基础路径内，拒绝点段、编码分隔符、反斜杠与空路径段，并关闭自动重定向；响应若
落到不同 Origin 或路径，执行记录为 error。

主请求一旦发出就会登记 cleanup。多个提取项中若只有部分成功，主用例仍因必需提取缺失而失败，已成功
提取的值只保留在该次 cleanup 局部快照中，不发布给下游用例，也不写入 Evidence。
单条断言求值出现异常时，其 Evidence 只记录异常类型；执行器仍继续处理其他断言与变量提取，使已经返回的
cleanup 标识可以用于本次局部回收。该主用例记录为 error，提取值仍不进入下游共享作用域。

## 示例

```yaml
schema_version: agentic-qa.api-cases.v1.2
artifact_type: api_automation_cases
status: needs_human_review
human_review_required: true
business_rules:
  - RULE-001
source_refs:
  - source_type: openapi
    source_path: sources/openapi.yml
    chunk_id: post-assist
    locator: POST /assist
    summary: 提交助力
    confidence: high
cases:
  - id: API-001
    title: 提交有效助力
    priority: P0
    contract_status: confirmed
    business_rule_refs: [RULE-001]
    review_status: needs_human_review
    review_questions: [测试账号与数据由人工选择]
    source_refs:
      - source_type: openapi
        source_path: sources/openapi.yml
        chunk_id: post-assist
        locator: POST /assist
        summary: 提交助力
        confidence: high
    pending: []
    request:
      method: POST
      path: /assist
      headers: {}
      query: {}
      body: {}
    assertions:
      - type: status_code
        expected: [200]
        path: null
      - type: json_field_equals
        path: $.data.accepted
        expected: true
      - type: header_equals
        path: Content-Type
        expected: application/json
      - type: response_time_ms_max
        expected: 1000
    variables: {}
    cleanup: []
review_questions:
  - 测试环境和数据由人工确认
```

完整字段约束见机器可读 [API Cases v1.2 JSON Schema](schemas/api-cases.v1.2.schema.json)。
历史 v1.1 published YAML 仍可读取，但新 Candidate 只生成 v1.2；v1.2 不再包含
`base_url_env`，Base URL 由本地项目配置和审核后的 workspace policy 决定。
v1.1 与 v1.2 都是已发布、按字节冻结的契约；普通模型代码生成不会覆盖它们。后续字段变化以
新的 Schema 版本发布，历史 v1.1 只通过只读兼容层解释。

## 常见问题

| 现象 | 系统行为 |
|---|---|
| 只有 PRD，没有 OpenAPI | 生成待确认场景，不确认 method/path |
| OpenAPI 使用外部 `$ref` | 检查返回不支持外部引用；来源先整合为自包含契约 |
| Candidate 已生成但执行工具拒绝 | `api.execute` 只读取人工审核后发布的 YAML |
| 环境名称类似 production | ExecutionProfile 校验返回错误 |
| POST 未在 allowlist | 执行证据记录为 blocked，不发送请求 |
| 静态 token 环境变量为空 | `api.execute` 返回认证配置错误，不发送用例请求 |
| 登录状态码或 token JSON 路径不匹配 | `api.execute` 返回认证错误，不发送后续用例请求 |
| 断言类型未知或参数错误 | Candidate 进入修订；历史 published 用例执行时记录 blocked 且不发送请求 |
| JSON 或响应头断言失败 | 证据保留类型与 SHA-256 摘要，不写入原始响应值 |
| 请求或响应失败 | 证据记录 error/failed，不自动生成已确认 Bug |
