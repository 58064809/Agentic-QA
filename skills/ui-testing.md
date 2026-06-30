# UI Testing Skill

## 目标

将 PRD、需求分析和测试用例转化为 Web/Android UI 自动化草稿。草稿只用于评审和后续实现，不代表已经执行。

## 设计要点

- 页面入口：明确页面 URL、入口路径、用户角色、前置数据和开关。
- 场景矩阵：覆盖主流程、表单校验、权限、状态、重复提交、接口异常和回归风险。
- Web：优先 Playwright，按页面或业务模块封装 Page Object。
- Android：命中 Android、安卓、模拟器、APK、appPackage、appActivity、UiAutomator2 时优先 Appium 2 + UiAutomator2。
- Fixtures：base_url、Appium Server、设备名、包名、Activity、账号和测试数据从环境变量或测试 fixture 读取。
- Web 选择器：优先 data-testid，其次 role/aria，再 text，最后稳定 CSS。
- Android 选择器：`resource-id > accessibility id/content-desc > UiSelector text/description > className + 层级辅助 > XPath 兜底 > 禁止坐标点击作为常规方案`。
- 等待：等待元素可见/可点击、页面主容器、接口响应，不使用固定 sleep。
- 断言：URL、文案、按钮状态、弹窗、列表、表单错误提示和关键接口响应。

## 不适合自动化

- 验证码、人脸识别、短信验证、风控拦截。
- 第三方支付、微信分享、App/小程序原生能力。
- 依赖真实线上数据或不可回滚的资金、库存、奖励场景。

## 安全约束

- 不保存真实 Cookie、Token、storage_state 或密钥。
- 不默认访问生产环境。
- 不绕过验证码、风控或权限控制。
