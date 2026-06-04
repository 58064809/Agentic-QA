---
version: v2.0
last_updated: 2025-07-19
difficulty: ★★☆☆☆
category: process
related_methods:
  - business-rule-extraction-skill
  - pytest-api-test-skill
  - test-design-skill
tags: [API, 契约分析, 接口测试]
---

# API 契约分析技能

## 概述

解析接口的请求/响应结构、字段约束、错误码体系、鉴权方案、幂等保证和限流规则，将接口契约转化为可断言的测试点。

适用于生成 API 测试计划和 pytest 脚本前的接口契约拆解。

## 适用时机

- 接口文档（OpenAPI / Swagger / 内部文档）就绪后
- 编写 API 自动化测试之前
- 接口变更评审时

## 前置知识

- 理解 HTTP 协议（方法、状态码、请求头）
- 能读懂 OpenAPI / Swagger / JSON Schema

## 操作步骤

### Step 1: 建立接口清单表

| 接口 | 方法 | 路径 | 鉴权 | 幂等 | 限流 |
|------|------|------|:----:|:----:|:----:|
| 登录 | POST | /api/v1/auth/login | 无 | 否 | 10/min |
| 获取用户 | GET | /api/v1/users/{id} | Bearer Token | 是 | 30/min |
| 创建订单 | POST | /api/v1/orders | Bearer Token | 是（idempotency-key） | 5/min |

### Step 2: 逐字段建立约束表

| 字段 | 位置 | 类型 | 必填 | 约束 | 断言点 |
|------|:----:|:----:|:----:|------|--------|
| phone | request.body | string | ✓ | 11位数字 | 格式校验 |
| password | request.body | string | ✓ | 6-20位 | 长度校验 |
| token | response.body | string | ✓ | JWT 格式 | 非空 + 格式 |
| code | response.body | string | ✓ | 业务码枚举 | 枚举值匹配 |

### Step 3: 区分 HTTP 状态码和业务状态码

| 层 | 代表 | 覆盖场景 |
|----|------|---------|
| HTTP 状态码 | 200/400/401/403/500 | 网络层面是否正常 |
| 业务状态码 | SUCCESS/LOCKED/TOKEN_EXPIRED | 业务逻辑是否正确 |

### Step 4: 梳理错误场景

| 错误类型 | 错误条件 | 预期 HTTP | 预期业务码 |
|---------|---------|:---------:|:---------:|
| 参数错误 | 缺少必填字段 | 400 | PARAM_MISSING |
| 鉴权失败 | token 过期 | 401 | TOKEN_EXPIRED |
| 鉴权失败 | token 格式错误 | 401 | TOKEN_INVALID |
| 权限不足 | 无权限访问 | 403 | FORBIDDEN |
| 资源不存在 | ID 不存在 | 404 | NOT_FOUND |
| 业务冲突 | 重复提交 | 409 | DUPLICATE_ORDER |
| 服务端错误 | 服务器异常 | 500 | INTERNAL_ERROR |

## 输出模板

### 接口断言表

| 断言点 | 检查内容 | 示例值 | 测试方法 |
|--------|---------|-------|---------|
| status_code | HTTP 状态码 | 200 | assert r.status_code == 200 |
| 业务码 | 响应中的 code 字段 | "SUCCESS" | assert r.json()["code"] == "SUCCESS" |
| 字段类型 | 响应字段类型 | string | isinstance(id, str) |
| 字段非空 | 关键字段不为 None/空 | token != "" | assert token is not None |
| 枚举值 | 枚举字段合法 | ["LOCKED","ACTIVE"] | assert status in VALID_STATUSES |
| 错误结构 | 错误响应的固定字段 | code + message | 检查 fields 齐全 |

## 自检清单

| 检查项 | 通过标准 | 自查 |
|--------|----------|:----:|
| 接口完整性 | 所有被测接口已列出 | □ |
| 字段完整性 | 请求和响应的必有字段已覆盖 | □ |
| 错误场景 | 400/401/403/404/409/500 已覆盖 | □ |
| 业务码 | HTTP 状态码和业务码已区分 | □ |
| 鉴权方案 | 所有接口的鉴权方式已注明 | □ |
| 幂等 | 幂等接口和不幂等接口已区分 | □ |
| 待确认 | 文档与实现不一致已标注 | □ |

## 常见误区

- ❌ 混淆 HTTP 状态码和业务状态码，只用 status_code 覆盖所有断言
- ❌ 忽略错误响应结构（只测成功，不测失败的结构）
- ❌ 忽略鉴权失败场景的多种类型（过期 / 格式错误 / 无 token）

## FAQ

**Q: 接口文档和实现不一致怎么办？**
A: 标记"待确认"，不要自行认定。在测试计划中列为风险点。

**Q: 一个接口有多个错误码，全部测试吗？**
A: 是的。每个错误码对应一个异常场景，全部覆盖是 API 测试的基本要求。

## 关联方法

- `business-rule-extraction-skill.md` — 将规则映射到 API 断言
- `pytest-api-test-skill.md` — 将契约转化为 pytest 脚本
- `test-design-skill.md` — 契约分析作为测试设计的输入

## 参考标准

- OpenAPI Specification 3.x
- RESTful API 设计规范
