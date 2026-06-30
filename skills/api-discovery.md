# API Discovery Skill

## 目标

从 Playwright 网络监听或 HAR 离线文件中提取业务接口候选，为 `api-test-draft` 提供补充证据。

## 方法

- 过滤静态资源：js、css、图片、字体、map 文件。
- 合并重复请求：按 Method + Path 聚合调用次数和状态码。
- 只保留 schema 摘要，不保存完整敏感响应体。
- 标记来源为 `playwright-network-capture`。
- 所有候选接口必须加入“需与 Swagger / Apifox 契约核对”的待确认项。

## 脱敏

- Header：Authorization、Cookie、Set-Cookie。
- 字段：token、access_token、refresh_token、session、JSESSIONID。
- PII：手机号、身份证、银行卡。
