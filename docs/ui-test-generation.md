# UI 自动化草稿生成

`ui_test_draft` 用于从 PRD、需求分析、测试用例和接口文档生成 Web/Android UI 自动化草稿。本阶段不启动浏览器、模拟器或真实设备，不访问真实环境。

## 工作流

```text
PRD / 需求分析 / 测试用例
  ↓
生成 UI 自动化草稿
  ↓
质量检查
  ↓
写入 runs/<run_id>/artifact-preview.md
  ↓
Review Gate
  ↓
promote 到 artifacts/ui-test-draft.md
```

## 输入

- `input/requirement.md`
- `input/api.md`
- `input/ui-flow.md`（可选）
- `artifacts/requirement-analysis.md`
- `artifacts/testcases.md`
- `prompts/ui-test-generation.md`
- `skills/ui-testing.md`

## 质量门

- 包含页面/入口清单。
- 包含 UI 自动化场景矩阵。
- 包含自动化脚本草稿。Web 优先 Playwright；命中 Android、安卓、模拟器、APK、appPackage、appActivity、UiAutomator2 等关键词时优先 Appium 2 + UiAutomator2。
- 包含选择器策略。
- 包含等待与断言策略。
- 包含不适合自动化或需人工确认的场景。
- 不出现“已执行 / 执行通过 / 实测通过”等执行结论。
- 不包含真实账号、token、Cookie 或密钥。
- 不默认连接任何未授权环境；执行环境必须由环境变量或测试配置显式指定。
- Android 草稿必须包含 Android Studio、Android SDK、Emulator、ADB、Appium 2、appium-uiautomator2-driver、APK 或 appPackage/appActivity，以及 `ANDROID_DEVICE_NAME`、`ANDROID_APP_PACKAGE`、`ANDROID_APP_ACTIVITY`、`APPIUM_SERVER_URL`。
