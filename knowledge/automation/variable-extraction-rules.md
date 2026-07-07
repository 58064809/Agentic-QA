# 变量提取规则

## 目标

变量提取用于在 YAML 用例中表达登录 token、业务 ID、订单号、状态值等动态数据的传递关系。第一版只定义规则，不新增复杂执行器。

## 变量来源

| 来源 | 写法 | 说明 |
|---|---|---|
| 环境变量 | `${ENV_NAME}` | base URL、账号、密码、租户、固定配置 |
| 用例提取 | `${case.variable}` | 从前置请求响应中提取 |
| fixture | `${fixture.name}` | 由 pytest fixture 提供 |
| 运行时生成 | `${runtime.uuid}` | 非敏感随机值 |

## 提取规则

- token、订单 ID、用户 ID 等动态字段应从响应中提取，不硬编码。
- 提取表达式必须写清 JSONPath 或来源字段。
- 下游用例引用前，必须说明依赖哪条前置用例或 fixture。
- 缺少前置数据准备方式时，写入 `review_questions`。

## 安全规则

- 不保存真实 token、Cookie、密码或个人敏感信息。
- 不把手机号、身份证、银行卡作为固定测试数据。
- 需要测试手机号等敏感格式时，使用脱敏样例或环境变量。

## 示例

```yaml
variables:
  extract:
    access_token: $.data.access_token
    order_id: $.data.order.id
  env:
    - TEST_LOGIN_USERNAME
    - TEST_LOGIN_PASSWORD
request:
  headers:
    Authorization: Bearer ${case.access_token}
```
