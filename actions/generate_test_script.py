from __future__ import annotations

import re
from typing import Any

from actions.automation_standards import API_TESTING_CHECKLIST
from actions.automation_standards import PLAYWRIGHT_CHECKLIST
from actions.requirement_parser import derive_business_rules
from actions.requirement_parser import extract_requirement_items
from actions.requirement_parser import split_questions


def _build_test_name(index: int) -> str:
    return f"test_requirement_{index:03d}"


def _safe_title(value: str, limit: int = 90) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _detect_script_target(user_text: str, requirement_items: list[str]) -> str:
    text = "\n".join([user_text, "\n".join(requirement_items)]).lower()
    if any(keyword in text for keyword in ("playwright", "e2e", "ui自动化", "页面自动化", "浏览器")):
        return "playwright"
    if any(keyword in text for keyword in ("api", "接口", "http", "rest", "schema", "契约")):
        return "api_pytest"
    return "pytest"


def _analysis_basis(requirement_context: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "requirement_docs": [doc["path"] for doc in requirement_context.get("selected_requirement_docs", [])],
        "prototype_assets": [asset["path"] for asset in requirement_context.get("selected_prototypes", [])],
    }


def _pytest_script(business_rules: list[str]) -> tuple[str, str, str, str]:
    lines = [
        "import pytest",
        "",
        "",
        "class TestGeneratedFromRequirement:",
    ]
    if not business_rules:
        lines.extend(
            [
                "    def test_placeholder(self):",
                '        """Provide a concrete requirement or PRD path before generating script."""',
                '        raise NotImplementedError("Requirement details are missing.")',
            ]
        )
    else:
        for index, rule in enumerate(business_rules, start=1):
            title = _safe_title(rule)
            lines.extend(
                [
                    "",
                    f"    @pytest.mark.case_{index}",
                    f"    def {_build_test_name(index)}(self):",
                    f'        """{title}"""',
                    f"        # TODO: prepare isolated test data for: {title}",
                    "        # TODO: execute API/page/DB action through project fixtures",
                    "        # TODO: assert observable behavior, persisted state, and logs",
                    '        raise NotImplementedError("Bind this case to real automation actions.")',
                ]
            )
    return "test_generated_from_requirement.py", "python", "pytest", "\n".join(lines) + "\n"


def _api_pytest_script(business_rules: list[str]) -> tuple[str, str, str, str]:
    lines = [
        "import pytest",
        "",
        "",
        "@pytest.fixture",
        "def api_client():",
        "    # TODO: return a project HTTP client with base_url, auth, retries, and logging.",
        '    raise NotImplementedError("Provide API client fixture.")',
        "",
        "",
        "class TestGeneratedApiRequirement:",
    ]
    for index, rule in enumerate(business_rules or ["补充接口需求后生成具体 API 自动化"], start=1):
        title = _safe_title(rule)
        lines.extend(
            [
                "",
                f"    @pytest.mark.api",
                f"    @pytest.mark.case_{index}",
                f"    def {_build_test_name(index)}(self, api_client):",
                f'        """{title}"""',
                "        # TODO: send request with valid, invalid, boundary, and auth variants.",
                "        # TODO: assert status code, response schema, business fields, and idempotency when relevant.",
                "        # TODO: verify server-side state or audit logs if this API changes data.",
                '        raise NotImplementedError("Bind this API case to real endpoint details.")',
            ]
        )
    return "test_generated_api_requirement.py", "python", "pytest-api", "\n".join(lines) + "\n"


def _playwright_script(business_rules: list[str]) -> tuple[str, str, str, str]:
    lines = [
        'import { test, expect } from "@playwright/test";',
        "",
        "// Generated skeleton. Bind selectors, routes, fixtures, and test data before enabling in CI.",
        "",
    ]
    for index, rule in enumerate(business_rules or ["补充页面需求后生成具体 Playwright 自动化"], start=1):
        title = _safe_title(rule)
        lines.extend(
            [
                f'test.skip("{title} @case_{index}", async ({{ page }}) => {{',
                f'  await test.step("Prepare data", async () => {{',
                f"    // TODO: create isolated data for: {title}",
                "  });",
                f'  await test.step("Execute user flow", async () => {{',
                "    // TODO: use role/name, label, text, or test id locators. Avoid brittle CSS/XPath.",
                "    // await page.goto('/path');",
                "  });",
                f'  await test.step("Assert observable result", async () => {{',
                "    // TODO: use web-first assertions. Do not use hard waits.",
                "    // await expect(page.getByRole('alert')).toBeVisible();",
                "  });",
                "});",
                "",
            ]
        )
    return "generated-requirement.spec.ts", "typescript", "playwright", "\n".join(lines)


def generate_test_script(user_text: str, requirement_context: dict[str, Any]) -> dict[str, Any]:
    items = extract_requirement_items(user_text, requirement_context)
    requirement_items, open_questions = split_questions(items)
    business_rules = derive_business_rules(requirement_items)[:8]
    target = _detect_script_target(user_text, requirement_items)

    if target == "playwright":
        file_name, language, framework, script = _playwright_script(business_rules)
        checklist = list(PLAYWRIGHT_CHECKLIST)
    elif target == "api_pytest":
        file_name, language, framework, script = _api_pytest_script(business_rules)
        checklist = list(API_TESTING_CHECKLIST)
    else:
        file_name, language, framework, script = _pytest_script(business_rules)
        checklist = [
            "每条测试独立准备数据，不依赖执行顺序",
            "断言用户可观察结果、接口结果、数据库状态和日志证据",
            "禁止为了通过而空断言或假通过，未绑定真实动作时保留 NotImplementedError",
        ]

    return {
        "_ok": True,
        "_metadata": {
            "requirement_count": len(requirement_items),
            "business_rule_count": len(business_rules),
            "script_target": target,
        },
        "task": "script_generation",
        "analysis_basis": _analysis_basis(requirement_context),
        "open_questions": open_questions,
        "automation_checklist": checklist,
        "recommended_file_name": file_name,
        "script_language": language,
        "script_framework": framework,
        "script_content": script,
    }
