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
    "Playwright 脚本草稿",
    "选择器策略",
    "等待与断言策略",
    "测试数据与环境配置",
    "不适合自动化或需人工确认的场景",
    "后续可接入网络抓包的页面动作",
]
EXECUTION_CLAIMS = ["已执行", "执行通过", "实测通过", "测试通过", "浏览器已运行"]
FORBIDDEN_ENV = ["生产环境", "线上环境", "prod 环境", "production"]
SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"(?i)(token|cookie|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}"),
]


def render_ui_test_draft_skeleton(state: QAWorkflowState) -> str:
    source_lines = _render_source_files(state)
    requirement = _path_content(state, "input/requirement.md")
    title = _first_heading(requirement) or "目标业务页面"
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

## 3. Playwright 脚本草稿

### fixtures 建议

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
- 依赖真实生产数据或无法回滚的资金/库存/奖励场景。
- 页面缺少稳定选择器、流程依赖人工审核或外部系统回调。

## 8. 后续可接入网络抓包的页面动作

- 打开目标页面并记录首屏接口调用链。
- 提交主流程表单并记录创建/更新接口。
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
    if "Playwright" not in artifact:
        state.quality_errors.append("UI 自动化草稿缺少 Playwright 脚本草稿。")
    if any(claim in artifact for claim in EXECUTION_CLAIMS):
        state.quality_errors.append("UI 自动化草稿不允许出现已执行或执行通过结论。")
    if any(env in artifact for env in FORBIDDEN_ENV):
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
