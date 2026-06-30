from __future__ import annotations

import re
from pathlib import Path

from runtime.graph.nodes.mvp_context_loader import TASK_UI_TEST_DRAFT
from runtime.graph.nodes.mvp_generation import (
    _build_rag_context,
    _generate_with_optional_llm,
    _path_content,
    _prd_prefix,
    _render_source_files,
    _upsert_artifact,
)
from runtime.graph.state import QAWorkflowState
from runtime.llm.prompt_builder import build_ui_test_prompt
from runtime.workspace import resolve_prd_path

REQUIRED_UI_SECTIONS = [
    "页面/入口清单",
    "UI 自动化场景矩阵",
    "自动化脚本草稿",
    "选择器策略",
    "等待与断言策略",
    "测试数据与环境配置",
    "不适合自动化或需人工确认的场景",
    "后续可接入网络抓包的页面动作",
]
EXECUTION_CLAIMS = ["已执行", "执行通过", "实测通过", "测试通过", "浏览器已运行"]
FORBIDDEN_ENV_PATTERNS = [
    re.compile(r"(在|到|访问|连接|执行|默认).{0,12}(生产环境|线上环境|production)", re.IGNORECASE),
    re.compile(
        r"(生产环境|线上环境|production).{0,12}(执行|访问|base_url|BASE_URL)",
        re.IGNORECASE,
    ),
]
ANDROID_KEYWORDS = (
    "android",
    "安卓",
    "模拟器",
    "apk",
    "apppackage",
    "appactivity",
    "uiautomator2",
)
ANDROID_REQUIRED_TERMS = (
    "Android Studio",
    "Android SDK",
    "Emulator",
    "ADB",
    "Appium 2",
    "appium-uiautomator2-driver",
    "ANDROID_DEVICE_NAME",
    "ANDROID_APP_PACKAGE",
    "ANDROID_APP_ACTIVITY",
    "APPIUM_SERVER_URL",
    "resource-id",
    "accessibility id",
    "UiSelector",
)
SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"(?i)(token|cookie|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}"),
]


def render_ui_test_draft_skeleton(state: QAWorkflowState) -> str:
    source_lines = _render_source_files(state)
    requirement = _path_content(state, "input/requirement.md")
    title = _first_heading(requirement) or "目标业务页面"
    if _prefers_android(state):
        return _render_android_ui_test_draft(title, source_lines)
    return _render_web_ui_test_draft(title, source_lines)


def _render_web_ui_test_draft(title: str, source_lines: str) -> str:
    return f"""---
status: needs_human_review
artifact_type: ui_test_draft
human_review_required: true
generated_by: agentic-qa-runtime
---

# UI 自动化测试草稿

## 1. 页面/入口清单

- {title} 页面入口：普通业务用户访问，base_url 已配置。
  账号由环境变量或 fixture 注入。待确认页面 URL、角色权限和 data-testid。
- 后台/管理入口候选：管理员或运营角色访问。
  后台账号和权限矩阵待补充。待确认是否存在后台页面和审核/配置动作。

## 2. UI 自动化场景矩阵

| 场景 | 测试类型 | 优先级 | 操作步骤 | 断言/待确认 |
|---|---|---|---|---|
| 主流程页面访问成功 | 正常/规则 | P0 | 打开页面并等待主要区域加载 | 核心元素可见；确认入口路径 |
| 表单必填项缺失提示 | 参数校验 | P1 | 清空必填字段并提交 | 错误提示可见；确认错误文案 |
| 无权限用户访问被拒绝 | 权限/认证 | P0 | 无权限态访问入口 | 无权限提示；确认鉴权策略 |
| 重复点击提交按钮 | 幂等/并发 | P1 | 快速点击两次 | 按钮禁用；确认防重策略 |
| 依赖接口失败时页面可恢复 | 接口异常 | P2 | 触发动作并等待错误 | 错误态可见；确认 mock 方式 |

## 3. 自动化脚本草稿

### Web / Playwright fixtures 建议

```python
import os

import pytest


@pytest.fixture
def base_url():
    value = os.getenv("AGENTIC_QA_UI_BASE_URL")
    if not value:
        pytest.skip("AGENTIC_QA_UI_BASE_URL 未配置，本阶段只生成草稿，不执行浏览器")
    return value.rstrip("/")


@pytest.fixture
def test_user():
    username = os.getenv("AGENTIC_QA_TEST_USER")
    password = os.getenv("AGENTIC_QA_TEST_PASSWORD")
    if not username or not password:
        pytest.skip("测试账号未配置，禁止在草稿中写真实账号或密码")
    return {{"username": username, "password": password}}
```

### Page Object 建议

```python
class TargetPage:
    def __init__(self, page, base_url):
        self.page = page
        self.base_url = base_url

    async def goto(self):
        await self.page.goto(f"{{self.base_url}}/待确认页面路径")
        await self.page.get_by_role("main").wait_for()

    async def submit(self):
        await self.page.get_by_test_id("submit-button").click()
```

### test_xxx.py 示例

```python
async def test_main_ui_flow(page, base_url, test_user):
    target = TargetPage(page, base_url)
    await target.goto()
    await page.get_by_role("button", name="待确认主按钮").click()
    await page.get_by_text("待确认成功文案").wait_for()
```

## 4. 选择器策略

- 优先 `data-testid`，由前端为核心按钮、表单、列表、弹窗、错误提示补充稳定标识。
- 其次使用 role / aria-label，例如 `get_by_role("button", name="提交")`。
- 再使用稳定可见 text，避免依赖动态文案。
- CSS 仅用于稳定语义 class 或固定容器。
- 禁止脆弱 XPath、`nth-child`、随机 class、截图坐标和纯顺序定位。

## 5. 等待与断言策略

- 等待页面加载：等待主容器、关键标题或首个接口响应完成。
- 等待接口响应：只监听测试环境接口，不保存真实 Cookie/Token。
- 等待元素可见/可点击：使用 locator 自带等待，避免固定 sleep。
- UI 断言：URL、文案、按钮状态、弹窗、列表、表单错误提示。
- 数据/接口断言建议：状态码、业务 code、关键字段、列表新增/状态变更。

## 6. 测试数据与环境配置

- base_url 从 `AGENTIC_QA_UI_BASE_URL` 读取，未配置时跳过，不默认访问任何环境。
- 账号从环境变量或测试数据 fixture 读取，不在仓库写真实账号、Cookie、Token。
- 禁止保存 storage_state、Cookie、Token 或密钥到仓库。
- 测试数据需使用隔离账号、可回滚业务对象和授权测试环境。

## 7. 不适合自动化或需人工确认的场景

- 验证码、人脸识别、短信验证、风控拦截。
- 第三方支付、微信分享、App/小程序原生能力。
- 依赖真实线上数据或无法回滚的资金/库存/奖励场景。
- 页面缺少稳定选择器、流程依赖人工审核或外部系统回调。

## 8. 后续可接入网络抓包的页面动作

- 打开目标页面并记录首屏接口调用链。
- 提交主流程表单并记录创建/更新接口。
- 触发异常提示并记录错误响应。
- 列表刷新、详情查看、状态流转动作可作为 API Discovery 候选输入。

## 来源文件

{source_lines}
"""


def _render_android_ui_test_draft(title: str, source_lines: str) -> str:
    return f"""---
status: needs_human_review
artifact_type: ui_test_draft
human_review_required: true
generated_by: agentic-qa-runtime
---

# UI 自动化测试草稿

## 1. 页面/入口清单

- {title} Android App 入口：使用 Android 模拟器或测试机，APK 或 appPackage/appActivity 待确认。
- Appium Server 入口：`APPIUM_SERVER_URL` 指向授权测试环境。
  本阶段只生成草稿，不启动设备、不执行用例。

## 2. UI 自动化场景矩阵

| 场景 | 测试类型 | 优先级 | 操作步骤 | 断言/待确认 |
|---|---|---|---|---|
| App 启动 | 正常/入口 | P0 | 启动 APK 或包名/Activity | 首屏可见；确认包名、Activity |
| 主流程点击与提交 | 正常/规则 | P0 | 按业务步骤点击、输入、提交 | 成功态文案或目标页面可见 |
| 必填项缺失提示 | 参数校验 | P1 | 清空必填项后提交 | 错误提示可见；确认文案 |
| 无权限态访问 | 权限/认证 | P0 | 使用隔离账号进入受限页面 | 无权限提示或跳转符合预期 |
| 网络异常恢复 | 接口异常 | P2 | 使用测试环境 mock 或断网策略触发失败 | 错误态可观察，可重试恢复 |

## 3. 自动化脚本草稿

### Android 前置条件

- Android Studio、Android SDK、Android Emulator 和 ADB 已安装并可在命令行访问。
- Appium 2 已安装，并安装 `appium-uiautomator2-driver`。
- 待测应用通过 APK 文件安装，或提供 `ANDROID_APP_PACKAGE` / `ANDROID_APP_ACTIVITY`。
- 环境变量：`ANDROID_DEVICE_NAME`、`ANDROID_APP_PACKAGE`、
  `ANDROID_APP_ACTIVITY`、`APPIUM_SERVER_URL`。

### pytest + Appium 示例

```python
import os

import pytest
from appium import webdriver
from appium.options.android import UiAutomator2Options


@pytest.fixture
def driver():
    server_url = os.getenv("APPIUM_SERVER_URL")
    device_name = os.getenv("ANDROID_DEVICE_NAME")
    app_package = os.getenv("ANDROID_APP_PACKAGE")
    app_activity = os.getenv("ANDROID_APP_ACTIVITY")
    if not all([server_url, device_name, app_package, app_activity]):
        pytest.skip("Android/Appium 环境变量未配置，本阶段只生成草稿，不执行用例")

    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.automation_name = "UiAutomator2"
    options.device_name = device_name
    options.app_package = app_package
    options.app_activity = app_activity
    driver = webdriver.Remote(server_url, options=options)
    yield driver
    driver.quit()


def test_android_main_flow(driver):
    driver.find_element("id", "待确认_resource_id").click()
    driver.find_element("accessibility id", "待确认_content_desc").click()
    assert driver.find_element("android uiautomator", 'new UiSelector().text("待确认成功文案")')
```

## 4. 选择器策略

- Android 定位优先级：
  `resource-id > accessibility id/content-desc > UiSelector text/description >
  className + 层级辅助 > XPath 兜底 > 禁止坐标点击作为常规方案`。
- 为核心按钮、输入框、列表项、弹窗和错误提示补充稳定 resource-id 或 content-desc。
- XPath 只作为临时兜底，禁止依赖动态层级、随机文本和屏幕坐标。

## 5. 等待与断言策略

- 等待 App 启动：等待目标 Activity 或首屏关键元素出现。
- 等待元素：使用显式等待，避免固定 sleep。
- UI 断言：页面标题、按钮状态、弹窗、Toast、列表数据、表单错误提示。
- 接口/数据断言建议：仅针对授权测试环境做状态码、业务 code、关键字段或状态流转校验。

## 6. 测试数据与环境配置

- Appium 连接从 `APPIUM_SERVER_URL` 读取，不默认连接任何环境。
- 设备名从 `ANDROID_DEVICE_NAME` 读取；
  包名和 Activity 从 `ANDROID_APP_PACKAGE`、`ANDROID_APP_ACTIVITY` 读取。
- APK 路径、测试账号、Cookie、Token 和密码不得写入仓库；使用环境变量或测试数据服务注入。
- 测试数据需使用隔离账号、可回滚业务对象和授权测试环境。

## 7. 不适合自动化或需人工确认的场景

- 验证码、人脸识别、短信验证、风控拦截。
- 第三方支付、系统权限弹窗、深度链接、推送通知和厂商 ROM 差异。
- 依赖真实线上数据或无法回滚的资金/库存/奖励场景。
- 页面缺少稳定 resource-id/content-desc，流程依赖人工审核或外部系统回调。

## 8. 后续可接入网络抓包的页面动作

- 启动 App 并记录首屏接口调用链。
- 完成主流程点击和提交并记录创建/更新接口。
- 触发异常提示并记录错误响应。
- 列表刷新、详情查看、状态流转动作可作为 API Discovery 候选输入。

## 来源文件

{source_lines}
"""


def ui_test_generation_node(state: QAWorkflowState) -> QAWorkflowState:
    if state.task_type != TASK_UI_TEST_DRAFT:
        return state
    state.record_node("ui_test_generation_node")
    if state.errors:
        return state
    prompt = build_ui_test_prompt(
        state.loaded_files,
        prd_prefix=_prd_prefix(state),
        rag_context=_build_rag_context(state),
        max_input_chars=int(state.llm.get("max_input_chars") or 32000),
    )
    state.warnings.extend(prompt.warnings)
    artifact = _generate_with_optional_llm(
        state,
        prompt=prompt.prompt,
        fallback=render_ui_test_draft_skeleton(state),
    )
    state.draft_artifacts["ui_test_draft"] = artifact
    state.draft_artifact = artifact
    output_path = state.output_paths.get("ui_test_draft")
    if output_path:
        state.output_path = output_path
        _upsert_artifact(
            state,
            name="ui_test_draft",
            artifact_type="ui_test_draft",
            output_path=output_path,
        )
    return state


def ui_test_quality_check_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    if state.task_type != TASK_UI_TEST_DRAFT:
        return state
    state.record_node("ui_test_quality_check_node")
    if state.errors:
        return state
    artifact = state.draft_artifacts.get("ui_test_draft") or ""
    if not artifact.strip():
        state.quality_errors.append("UI 自动化草稿为空。")
        return state
    for section in REQUIRED_UI_SECTIONS:
        if not _has_section(artifact, section):
            state.quality_errors.append(f"UI 自动化草稿缺少章节: {section}")
    if not any(keyword in artifact for keyword in ("Playwright", "Appium", "UiAutomator2")):
        state.quality_errors.append("UI 自动化草稿缺少 Playwright 或 Appium 脚本草稿。")
    if _prefers_android(state) or "UiAutomator2" in artifact:
        missing_terms = [term for term in ANDROID_REQUIRED_TERMS if term not in artifact]
        if missing_terms:
            state.quality_errors.append(
                "Android UI 自动化草稿缺少关键配置或策略: " + "、".join(missing_terms)
            )
    if any(claim in artifact for claim in EXECUTION_CLAIMS):
        state.quality_errors.append("UI 自动化草稿不允许出现已执行或执行通过结论。")
    if any(pattern.search(artifact) for pattern in FORBIDDEN_ENV_PATTERNS):
        state.quality_errors.append("UI 自动化草稿不允许建议在生产环境执行。")
    if any(pattern.search(artifact) for pattern in SECRET_PATTERNS):
        state.quality_errors.append("UI 自动化草稿疑似包含真实账号、token、Cookie 或密钥。")
    _check_output_path(state, repo_root)
    return state


def _first_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line.lstrip("#").strip()
    return None


def _prefers_android(state: QAWorkflowState) -> bool:
    haystack = "\n".join(
        [
            state.user_input,
            *[str(content) for content in state.loaded_files.values()],
        ]
    ).lower()
    return any(keyword in haystack for keyword in ANDROID_KEYWORDS)


def _has_section(markdown: str, section: str) -> bool:
    return bool(re.search(rf"^##\s+\d+\.\s+{re.escape(section)}\s*$", markdown, re.MULTILINE))


def _check_output_path(state: QAWorkflowState, repo_root: Path) -> None:
    output_path = state.output_paths.get("ui_test_draft")
    if not output_path:
        state.quality_errors.append("缺少 UI 自动化草稿输出路径。")
        return
    prd_path = resolve_prd_path(repo_root, state.prd_path)
    if not (repo_root / Path(output_path)).resolve().is_relative_to(prd_path.resolve()):
        state.quality_errors.append("UI 自动化草稿输出路径必须位于目标 PRD 工作区内。")
    expected_suffix = "/runs/" + (state.run_id or "runtime") + "/artifact-preview.md"
    if not Path(output_path).as_posix().endswith(expected_suffix):
        state.quality_errors.append(
            "UI 自动化草稿输出路径不符合约定: runs/<run_id>/artifact-preview.md"
        )
