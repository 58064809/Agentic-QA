# 项目配置

仓库根目录的 `agentic-qa.local.yml` 是唯一人工配置入口。首次使用先执行：

```powershell
python -m harness config init
```

命令从 `agentic-qa.local.example.yml` 创建文件，已有文件时拒绝覆盖。真实配置已被 Git 忽略，且不属于
`local-sources/`、workspace、Prompt 或报告的内容。

## 配置分区

| 分区 | 在文件中直接填写 | 仍从环境变量读取 |
|---|---|---|
| `model` | Provider、模型名、Base URL、超时、输出上限 | `api_key_env` 指向的实际模型 Key |
| `rag` | Provider、Base URL、模型、切块参数 | `api_key_env` 指向的实际 RAG Key；本地词法检索不需要 |
| `postgres` | Host、端口、库、用户、密码、超时、最大行数 | 无 |
| `test_management` | TestRail/Qase 地址、用户及凭据 | 无 |
| `workspace_defaults` | 默认质量策略、额外来源根 | 无 |
| `runtime` | cleanup journal 的本地加密 Key，由命令生成 | 无 |
| `api.services` | 来源目录、环境、Base URL、认证、AES Key、Token 与安全策略 | 无 |

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
  username: qa@example.test
  api_key: local-value
```

Qase 配置示例：

```yaml
test_management:
  provider: qase
  base_url: https://api.qase.io
  api_token: local-value
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
          timeout_seconds: 30
          auth:
            login:
              kind: sms
              request_path: /member/app/login/phoneLogin
              tel_code: "+86"
              phone: ""
              sms_code: "000000"
              encryption:
                algorithm: aes-128-cbc-pkcs7-base64-iv-prefix
                key: ""
                fields: [phone, smsCode]
              success_condition: {json_path: $.code, expected: 1000}
              token_json_path: $.data.userInfo.accessToken
              injection: {name: accesstoken, prefix: ""}
            fallback_token: ""
```

认证选择是 fail-closed：登录字段全部填写时使用登录；全部清空时以非空 `fallback_token` 作为认证；只填一部分
直接失败，Token 不会掩盖错误。`dev`/`test` 短信码只接受 `000000`。AES-128 Key 校验为正好 16 字节。
`pro`、`prod`、`production`、`live` 环境本期全部拒绝。

`config doctor` 校验整个文件；`api doctor` 进一步校验选定服务的 OpenAPI、人工用例和认证选择。配置
错误的命令退出码为 2，且不会创建 workspace、run 或发送请求。

`config init` 会自动生成 `runtime.cleanup_journal_key`。已有配置缺少该值时执行
`python -m harness config runtime-key init`；命令只补缺失的 AES-256-GCM Key，绝不覆盖现有值。
每个确认的 `POST`、`PUT`、`PATCH` 或 `DELETE` 业务用例默认需要声明 cleanup；缺少时 Candidate 会被质量门拒绝。确认无副作用时，按
`METHOD /path-template` 精确加入对应环境的 `cleanup_exempt_operations`；项目登录隐式豁免。

## 持久化边界

workspace 只保存服务名、环境、非敏感执行策略与结构 SHA-256。手机号、密码、验证码、AES Key、
Token、数据库密码和连接器凭据每次运行都从根配置重新读取。凭据值变化沿用已有 Review；Base URL、
trusted Origin、方法 allowlist、登录路径、算法或 Token 注入规则变化会阻止请求，并进入新的 prepare 和
Review 流程。

`GITHUB_TOKEN` 与 `AGENTIC_QA_GITHUB_TOKEN_ENV` 当前均不是运行时配置，Harness 不读取它们。
