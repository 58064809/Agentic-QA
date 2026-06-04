---
status: needs_human_review
human_review_required: true
artifact_type: api_test_plan_draft
generated_by: Codex
---

# 手机号密码登录 API 测试计划草稿

## 测试范围

- `POST /api/v1/auth/login`
- `GET /api/v1/profile`

## 测试数据设计

| 数据 | 用途 | 来源 | 备注 |
|---|---|---|---|
| `LOGIN_API_BASE_URL` | 非生产环境 base URL | 环境变量 | 未设置时 pytest 脚本 skip |
| `LOGIN_TEST_PHONE` | 可登录手机号 | 环境变量 | 禁止提交真实手机号 |
| `LOGIN_TEST_PASSWORD` | 正确密码 | 环境变量 | 禁止提交真实密码 |
| `LOGIN_WRONG_PASSWORD` | 错误密码 | 环境变量 | 默认使用占位值 |

## 环境变量说明

```text
LOGIN_API_BASE_URL=https://example-test-env.local
LOGIN_TEST_PHONE=13800138000
LOGIN_TEST_PASSWORD=<secret>
LOGIN_WRONG_PASSWORD=wrong-password
```

## 断言策略

- 登录成功：断言 HTTP 状态码、业务码、`access_token`、`token_type`、`expires_in`。
- 密码错误：断言错误码 `INVALID_CREDENTIALS` 或等价错误响应。
- token 过期：断言 `TOKEN_EXPIRED` 或重新登录提示。
- 无环境变量：测试 skip，不请求真实服务。

## 禁止事项

- 禁止连接生产环境。
- 禁止在脚本中写入真实手机号、密码、token。
- 禁止把草稿脚本视为已审核自动化。

## 待人工确认

- 错误响应是否使用 HTTP 状态码还是统一 HTTP 200。
- 锁定剩余时间字段名。
- token 有效期和 refresh 机制。
