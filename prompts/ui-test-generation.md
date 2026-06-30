# UI 自动化草稿生成 Prompt

生成 `ui_test_draft` 候选产物，只输出可审核草稿，不启动浏览器、模拟器或真实设备。

## 输出结构

- 页面/入口清单
- UI 自动化场景矩阵
- 自动化脚本草稿
- 选择器策略
- 等待与断言策略
- 测试数据与环境配置
- 不适合自动化或需人工确认的场景
- 后续可接入网络抓包的页面动作

## 约束

- 不得声称已执行浏览器、已登录、已通过或实测通过。
- 不写真实账号、真实 token、真实 Cookie 或密钥。
- Web 场景优先 Playwright；Android/安卓/模拟器/APK/appPackage/appActivity/UiAutomator2 场景优先 Appium 2 + UiAutomator2。
- Web base_url、账号、密码必须来自环境变量或 fixture。
- Android 草稿必须包含 Android Studio、Android SDK、Emulator、ADB、Appium 2、appium-uiautomator2-driver、APK 或 appPackage/appActivity。
- Android 环境变量使用 `ANDROID_DEVICE_NAME`、`ANDROID_APP_PACKAGE`、`ANDROID_APP_ACTIVITY`、`APPIUM_SERVER_URL`。
- Web 选择器优先级：`data-testid > role/aria > text > 稳定 CSS`。
- Android 选择器优先级：`resource-id > accessibility id/content-desc > UiSelector text/description > className + 层级辅助 > XPath 兜底 > 禁止坐标点击作为常规方案`。
- 禁止脆弱 XPath、`nth-child`、截图坐标、随机 class。
- 必须区分适合自动化与不适合自动化的场景。
