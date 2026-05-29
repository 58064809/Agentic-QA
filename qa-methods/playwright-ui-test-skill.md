---
version: v2.0
last_updated: 2025-07-19
difficulty: ★★☆☆☆
category: output
related_methods:
  - scenario-modeling-skill
  - test-design-skill
tags: [Playwright, UI测试, 自动化脚本]
---

# Playwright UI 测试技能

## 概述

使用 Playwright 框架将 UI 测试用例转化为稳定的自动化草稿，包括选择器策略、等待策略、断言规范和失败诊断策略。

## 适用时机

- 端到端业务流程（场景建模）已就绪
- 手工 UI 用例需要自动化

## 前置知识

- 掌握 Playwright 基础（page、locator、assertions）
- 了解被测应用的 DOM 结构和前端框架（React / Vue / 原生）

## 操作步骤

### Step 1: 选择器策略

| 优先级 | 选择器类型 | 示例 | 稳定性 |
|:------:|-----------|------|:------:|
| 1 | 测试 ID | `page.getByTestId('login-btn')` | ⭐⭐⭐ |
| 2 | Role + 名称 | `page.getByRole('button', { name: '登录' })` | ⭐⭐⭐ |
| 3 | Label | `page.getByLabel('手机号')` | ⭐⭐⭐ |
| 4 | Placeholder | `page.getByPlaceholder('请输入手机号')` | ⭐⭐ |
| 5 | Text | `page.getByText('立即注册')` | ⭐⭐ |
| 6 | CSS | `page.locator('.btn-primary')` | ⭐ |
| 7 | XPath | `page.locator('//button[1]')` | ❌ 避免使用 |

### Step 2: 等待策略

```python
# 推荐：自动等待（缺省行为）
await page.getByTestId("login-btn").click()  # Playwright 自动等待可见/可操作

# 显式等待（必要时使用）
await page.wait_for_selector("[data-testid='user-profile']", state="visible")

# 网络等待（API 产生的结果）
await page.wait_for_response("**/api/v1/user/profile")
```

| 策略 | 说明 |
|------|------|
| 自动等待 | Playwright 默认等待元素可见、启用、稳定（推荐） |
| 显式等待 | `wait_for_selector` / `wait_for_url`（特殊场景） |
| sleep | 禁止使用 `page.wait_for_timeout` / time.sleep（除了调试） |

### Step 3: 断言规范

```python
# 业务断言（推荐）
await expect(page.get_by_test_id("welcome-msg")).to_have_text("欢迎回来")

# 状态断言
await expect(page.get_by_test_id("error-toast")).to_be_visible()

# URL 断言
await expect(page).to_have_url("**/dashboard")
```

| 断言类型 | 示例 | 说明 |
|---------|------|------|
| 内容断言 | `to_have_text` / `to_contain_text` | 文本内容 |
| 可见性断言 | `to_be_visible` / `not_to_be_visible` | 元素显示/隐藏 |
| 状态断言 | `to_be_enabled` / `to_be_disabled` | 元素可用/禁用 |
| URL 断言 | `to_have_url` / `not_to_have_url` | 页面跳转 |

### Step 4: 失败诊断策略

```python
# conftest.py — 失败自动截图
@pytest.fixture
def page(page):
    yield page
    # 测试失败时截图
    if hasattr(request.node, "rep_call") and request.node.rep_call.failed:
        page.screenshot(path=f"screenshots/{request.node.name}_{int(time.time())}.png")
```

## 输出模板

### 测试文件结构

```python
# test_login.py
import pytest
from playwright.sync_api import Page, expect

def test_login_success(page: Page):
    page.goto("/login")
    page.get_by_test_id("phone-input").fill("13800138000")
    page.get_by_test_id("password-input").fill("validPass123")
    page.get_by_test_id("login-btn").click()
    expect(page.get_by_test_id("welcome-msg")).to_have_text("欢迎回来")
```

## 自检清单

| 检查项 | 通过标准 | 自查 |
|--------|----------|:----:|
| 选择器稳定 | 不使用脆弱的 CSS/XPath 层级选择器 | □ |
| 等待策略 | 不使用 time.sleep | □ |
| 断言业务结果 | 断言反映业务目标，不仅是元素存在 | □ |
| 单个目标 | 每个测试覆盖一个关键目标 | □ |
| 截图保留 | 失败时保留截图/trace | □ |
| 异步等待 | 异步渲染已完成再交互 | □ |

## 常见误区

- ❌ 使用脆弱 CSS 层级选择器 `.container > div:nth-child(2) > button`
- ❌ 缺少截图或失败诊断策略（失败后不留证据）
- ❌ 使用 time.sleep 代替等待（不稳定且慢）
- ❌ 一个测试覆盖过多目标（难以定位失败点）

## FAQ

**Q: 验证码、短信怎么办？**
A: 必须标注"不可自动化"。可以：
- 使用测试环境的关闭验证码配置
- 使用固定测试验证码（如 888888）
- 通过 API 直接设置登录状态绕过 UI 验证

**Q: 第三方登录（微信/Google）如何处理？**
A: 标注"不可自动化"，在测试计划中标记为手动测试，UI 自动化只覆盖本系统的登录流程。

## 关联方法

- `scenario-modeling-skill.md` — 场景作为 UI 自动化脚本的业务输入
- `test-design-skill.md` — 优先级决策

## 参考标准

- Playwright 官方文档（最佳实践章节）
- Google Testing Blog — UI Test Best Practices
