# 项目配置

仓库根目录的 `agentic-qa.local.yml` 是唯一人工配置入口。首次使用先执行：

```powershell
python -m harness config init
```

命令从 `agentic-qa.local.example.yml` 创建文件，已有文件时拒绝覆盖。真实配置已被 Git 忽略，且不属于
`local-sources/`、workspace、Prompt 或报告的内容。旧版配置若仍把密码、Token 或 AES Key 直接写在
业务字段中，先执行 `python -m harness config secrets migrate`；命令把原值移入统一 Secret Provider，
再将业务字段替换为 `secret://<reference>`，create-once 且不覆盖已有 provider。

## Secret Provider

所有敏感配置字段采用完整的 `secret://` 引用，不支持在字符串中插值。单机默认把人工值集中放在同一文件
顶部，因此仍只有一个配置入口：

```yaml
secrets:
  provider: local
  values:
    postgres.password: "<本机密码>"
    runtime.cleanup_journal_key: "<config init 自动生成>"
    api.member-service.dev.auth.login.phone: "<测试手机号>"
    api.member-service.dev.auth.login.sms_code: "000000"
    api.member-service.dev.auth.login.encryption.key: "<16 字节测试 Key>"
    api.member-service.dev.auth.fallback_token: ""
```

CI 或团队环境可切换为 `provider: environment`，映射的是“引用名 → 环境变量名”，业务字段保持不变：

```yaml
secrets:
  provider: environment
  variables:
    postgres.password: AGENTIC_QA_SECRET_POSTGRES_PASSWORD
    runtime.cleanup_journal_key: AGENTIC_QA_SECRET_CLEANUP_KEY
    api.member-service.dev.auth.fallback_token: AGENTIC_QA_SECRET_MEMBER_TOKEN
```

模型实际 Key 与远程 RAG 实际 Key 继续由各自 `api_key_env` 读取，不进入该 provider。Secret Provider
只在进程内解析；workspace、执行计划、事件、Evidence 和 Allure 只保存结构或摘要。

## 配置分区

| 分区 | 在文件中直接填写 | 仍从环境变量读取 |
|---|---|---|
| `model` | Provider、模型名、Base URL、超时、输出上限 | `api_key_env` 指向的实际模型 Key |
| `rag` | Provider、Base URL、模型、切块参数 | `api_key_env` 指向的实际 RAG Key；本地词法检索不需要 |
| `secrets` | local 值，或 CI 环境变量映射 | environment provider 声明的实际值 |
| `postgres` | Host、端口、库、用户、`secret://` 密码引用、超时、最大行数 | 无 |
| `test_management` | TestRail/Qase 地址及 `secret://` 凭据引用 | 无 |
| `workspace_defaults` | 默认质量策略、额外来源根 | 无 |
| `runtime` | cleanup journal Key 的 `secret://` 引用 | 无 |
| `api.services` | 来源目录、环境、安全策略及认证值的 `secret://` 引用 | 无 |

以下三类实际 Key 留在环境变量，名称由配置中的 `api_key_env` 决定：`DEEPSEEK_API_KEY`、
`OPENAI_API_KEY`、`RAG_API_KEY`。

```powershell
$env:DEEPSEEK_API_KEY = "<模型 Key>"
$env:OPENAI_API_KEY = "<仅在 model.api_key_env 指向它时填写>"
$env:RAG_API_KEY = "<仅在使用远程 RAG 时填写>"
```

旧的 `AGENTIC_QA_*`、`PG_LOCAL_*`、TestRail/Qase 以及 API 凭据环境变量不再读取。

## 完整契约

配置 Schema 是 `agentic-qa.local-config.v1`，未知字段会被拒绝。实际字段以根目录
`agentic-qa.local.example.yml` 为准。模型和 RAG 分区保存 Key 的环境变量名称；填写 `api_key`、
`token` 等直接 Key 字段会导致校验失败。

TestRail 配置示例：

```yaml
test_management:
  provider: testrail
  base_url: https://testrail.example.test
  username: secret://test_management.username
  api_key: secret://test_management.api_key
```

Qase 配置示例：

```yaml
test_management:
  provider: qase
  base_url: https://api.qase.io
  api_token: secret://test_management.api_token
```

不使用测试管理系统时保持 `provider: none`。

## API 服务与环境

每个服务声明唯一的仓库内相对目录。目录内容是完整 OpenAPI/Apifox 导出和标准人工用例；旧
`api-test.yml` 会成为明确的迁移错误。

```yaml
api:
  services:
    member-service:
      source_directory: local-sources/api/member-service
      environments:
        dev:
          base_url: https://gateway-app-dev.nexuscube.cn
          trusted_origins: [https://gateway-app-dev.nexuscube.cn]
          allowed_http_methods: [GET, POST]
          cleanup_exempt_operations: []
          isolation:
            mode: namespace
            namespace: {location: header, name: X-Test-Namespace, prefix: aqa}
          operation_policies:
            POST /orders:
              classification: mutation_idempotent
              idempotency_header: Idempotency-Key
          timeout_seconds: 30
          auth:
            login:
              kind: sms
              request_path: /member/app/login/phoneLogin
              tel_code: "+86"
              phone: secret://api.member-service.dev.auth.login.phone
              sms_code: secret://api.member-service.dev.auth.login.sms_code
              encryption:
                algorithm: aes-128-cbc-pkcs7-base64-iv-prefix
                key: secret://api.member-service.dev.auth.login.encryption.key
                fields: [phone, smsCode]
              success_condition: {json_path: $.code, expected: 1000}
              token_json_path: $.data.userInfo.accessToken
              injection: {name: accesstoken, prefix: ""}
            fallback_token: secret://api.member-service.dev.auth.fallback_token
```

认证选择是 fail-closed：登录字段全部填写时使用登录；全部清空时以非空 `fallback_token` 作为认证；只填一部分
直接失败，Token 不会掩盖错误。`dev`/`test` 短信码只接受 `000000`。AES-128 Key 校验为正好 16 字节。
`pro`、`prod`、`production`、`live` 环境本期全部拒绝。

`config doctor` 校验整个文件；`api doctor` 进一步校验选定服务的 OpenAPI、人工用例和认证选择。配置
错误的命令退出码为 2，且不会创建 workspace、run 或发送请求。

`config init` 会在 local provider 中自动生成 `runtime.cleanup_journal_key` 对应的值。已有 provider 缺少该值时执行
`python -m harness config runtime-key init`；命令只补缺失的 AES-256-GCM Key，绝不覆盖现有值。
`operation_policies` 按精确的 `METHOD /path-template` 分类。默认 GET 为 `read_only`，POST/PUT/PATCH/DELETE
为 `mutation_cleanup`；也可明确声明 `mutation_idempotent` 或 `mutation_manual`。幂等 Header 只有服务契约或
团队确认支持时才能配置，Harness 只生成确定性 key，不因此自动重试写请求。旧
`cleanup_exempt_operations` 只作为 `read_only` 兼容入口，新配置应使用 operation policy。项目登录隐式豁免。

`isolation.mode: namespace` 为每个 execution 生成确定性命名空间，并通过已审核的 Header、query 或 body
根字段注入；事件与执行计划只保存其 SHA-256。`shared` 是默认值。隔离与清理优先级是：可销毁环境、
execution namespace、正常 teardown、加密恢复 journal、最后人工核对；当前内置执行器实现 namespace 与
后续三层，可销毁环境由 CI/平台在 Harness 外部供应并在执行结束后回收。

## 持久化边界

workspace 只保存服务名、环境、非敏感执行策略与结构 SHA-256。手机号、密码、验证码、AES Key、
Token、数据库密码和连接器凭据每次运行都通过 Secret Provider 重新解析。凭据值变化沿用已有 Review；Base URL、
trusted Origin、方法 allowlist、登录路径、算法或 Token 注入规则变化会阻止请求，并进入新的 prepare 和
Review 流程。

`GITHUB_TOKEN` 与 `AGENTIC_QA_GITHUB_TOKEN_ENV` 当前均不是运行时配置，Harness 不读取它们。
