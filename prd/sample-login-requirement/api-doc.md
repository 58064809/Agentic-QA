# 手机号密码登录 API 文档示例

## POST /api/v1/auth/login

### 请求体

```json
{
  "phone": "13800138000",
  "password": "correct-password"
}
```

### 成功响应

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "access_token": "example.jwt.token",
    "token_type": "Bearer",
    "expires_in": 7200
  }
}
```

### 失败响应

| 场景 | HTTP 状态码 | 业务码 | message |
|---|---:|---|---|
| 手机号格式错误 | 400 | `INVALID_PHONE` | 手机号格式不正确 |
| 密码错误 | 401 | `INVALID_CREDENTIALS` | 手机号或密码错误 |
| 账号锁定 | 423 | `ACCOUNT_LOCKED` | 账号已锁定，请稍后再试 |

## GET /api/v1/profile

访问用户资料需要 `Authorization: Bearer <token>`。

### token 过期响应

```json
{
  "code": "TOKEN_EXPIRED",
  "message": "登录已过期，请重新登录",
  "data": null
}
```

## 待确认项

- 锁定剩余时间字段是否必须返回。
- token 过期时间是否固定为 7200 秒。
- 错误响应是否统一使用 HTTP 200 加业务码。
