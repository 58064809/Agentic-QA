# API Testing Skill

## 目标

将已确认需求和测试用例转化为可审核的接口测试计划、断言策略、pytest + requests 脚本草稿和 YAML 接口用例草稿。本技能只指导草稿生成，不代表可以执行真实接口请求。

## 分析维度

- 接口契约：Method、URL、Headers、Query、Body、Response、错误码。
- 鉴权认证：未登录、token 过期、token 格式错误、权限不足、数据归属。
- 参数校验：必填、类型、格式、枚举、长度、金额、数量、时间、边界值。
- 业务规则：状态流转、活动开关、库存/次数/奖励、订单/支付、风控限制。
- 幂等并发：重复提交、接口重放、并发请求、幂等键、去重逻辑。
- 异常恢复：上游失败、超时、弱网、5xx、降级和补偿。
- 数据一致性：接口响应、数据库状态、Redis 缓存、MQ 消息、日志审计一致。

## 草稿要求

- 有接口文档时，以接口文档为事实来源。
- OpenAPI / Swagger / Apifox 导出文件需先归一化为接口清单、参数、requestBody、response 和 securitySchemes。
- 没有接口文档时，只输出接口候选点，不把推断内容写成确定事实。
- pytest + requests 示例必须默认通过环境变量读取 base URL 和鉴权信息。
- 脚本草稿应在环境变量缺失时 `pytest.skip`，避免误请求真实服务。
- YAML 接口用例草稿必须跟随 `api_test_draft` 进入同一 Review Gate，未确认前只能作为候选用例。
- YAML 用例只写相对 path，base URL 通过 `AGENTIC_QA_BASE_URL` 注入。
- YAML 中的 token、Cookie、账号、密码等只能使用 `${ENV_NAME}` 占位。
- YAML 必须记录 `business_rules` 和每条用例的 `business_rule_refs`，以便人审时核对 PRD / Swagger / 业务规则。
- 不写真实 token、Cookie、密钥、生产域名或真实敏感数据。

## 断言建议

- HTTP 状态码：2xx、400、401、403、404、409、429、5xx。
- 业务 code：成功、参数错误、未授权、状态不允许、重复提交、依赖失败。
- message：用户可理解，不泄露账号状态、内部异常或敏感信息。
- data：关键字段存在、类型正确、枚举合法、金额/数量/时间精度正确。
- DB：状态、金额、库存、次数、奖励、订单或业务记录是否正确更新。
- Redis：幂等键、锁、限流、缓存失效是否符合规则。
- MQ：消息 topic、事件字段、去重键、重试/补偿语义是否正确。
