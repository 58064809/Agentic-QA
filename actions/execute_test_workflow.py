from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from actions.analyze_pytest_result import analyze_pytest_result
from actions.case_binding import apply_auto_bindings
from actions.case_binding import merge_binding_overrides
from actions.generate_test_cases import generate_test_cases
from actions.run_pytest import run_pytest
from tools.env_config import parse_env_text

ROOT = Path(__file__).resolve().parents[1]


def _safe_slug(value: str, fallback: str = "requirement") -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_").lower()
    return slug or fallback


def _requirement_root(workspace_root: Path, requirement_context: dict[str, Any]) -> Path:
    package = requirement_context.get("requirement_package") or {}
    relative_root = package.get("relative_root")
    if relative_root:
        return workspace_root / relative_root
    return workspace_root


def _package_name(requirement_root: Path, requirement_context: dict[str, Any]) -> str:
    package = requirement_context.get("requirement_package") or {}
    return package.get("name") or requirement_root.name or "requirement"


def _normalize_case(raw_case: dict[str, Any], columns: list[str], index: int) -> dict[str, Any]:
    values = [str(raw_case.get(column, "")).strip() for column in columns]
    while len(values) < 10:
        values.append("")
    case_id = values[0] or f"CASE-{index:03d}"
    title = values[3] or case_id
    return {
        "case_id": case_id,
        "module": values[1],
        "priority": values[2] or "P1",
        "title": title,
        "precondition": values[4],
        "test_data": values[5],
        "steps": values[6],
        "expected": values[7],
        "checkpoints": values[8],
        "source": values[9],
        "binding": {
            "status": "pending",
            "type": "unbound",
            "target": "",
            "reason": "missing API/page object/fixture/data binding",
        },
    }


def _build_execution_plan(cases_result: dict[str, Any]) -> dict[str, Any]:
    columns = list(cases_result.get("columns", []))
    cases = [
        _normalize_case(raw_case, columns, index)
        for index, raw_case in enumerate(cases_result.get("cases", []), start=1)
    ]
    return {
        "version": 1,
        "case_count": len(cases),
        "ready_count": 0,
        "pending_count": len(cases),
        "cases": cases,
        "binding_contract": {
            "api": ["profile", "method", "path", "headers", "json", "expected_status", "assertions"],
            "api_flow": ["profile", "steps", "db_assertions", "cleanup"],
            "scenario": ["profile", "data", "generators", "steps", "db_assertions", "cleanup"],
            "page": ["page_object", "selector_strategy", "user_role", "assertions", "cleanup"],
            "db_assert": ["engine", "pg_dsn_env", "sqlite_path", "readonly_select_query", "expected_row_count"],
            "fixture": ["fixture_name", "input_data", "expected_result"],
        },
    }


def _env_template(package_name: str) -> str:
    return "\n".join(
        [
            "# Fill this file before enabling real business automation.",
            f"requirement: {package_name}",
            "environment:",
            '  name: "local"',
            '  active_profile: "platform_admin"',
            '  base_url: ""',
            '  api_base_url: ""',
            "profiles:",
            "  platform_admin:",
            "    environment:",
            '      name: "platform_admin"',
            '      api_base_url: ""',
            "    auth:",
            '      mode: "header"',
            '      token: ""',
            '      token_env: "PLATFORM_ADMIN_TOKEN"',
            '      header_name: "accesstoken"',
            '      token_type: "Bearer"',
            "    headers:",
            '      environment: "1"',
            '      source: "99"',
            "    cookies:",
            "  merchant_admin:",
            "    environment:",
            '      name: "merchant_admin"',
            '      api_base_url: ""',
            "    auth:",
            '      mode: "header"',
            '      token: ""',
            '      token_env: "MERCHANT_ADMIN_TOKEN"',
            '      header_name: "accesstoken"',
            '      token_type: "Bearer"',
            "    headers:",
            '      environment: "1"',
            '      source: "1"',
            "    cookies:",
            "  c_app:",
            "    environment:",
            '      name: "c_app"',
            '      api_base_url: ""',
            "    auth:",
            '      mode: "bearer"',
            '      token: ""',
            '      token_env: "C_APP_TOKEN"',
            '      token_type: "Bearer"',
            "    headers:",
            "    cookies:",
            "accounts:",
            '  merchant: ""',
            '  finance: ""',
            '  operator: ""',
            "auth:",
            '  token: ""',
            '  token_env: "TEST_AUTH_TOKEN"',
            '  token_type: "Bearer"',
            "database:",
            "  enabled: false",
            '  db_engine: "postgres"',
            '  pg_dsn: ""',
            '  pg_dsn_env: "TEST_PG_DSN"',
            '  sqlite_path: ""',
            "redis:",
            "  enabled: false",
            '  dsn_env: "TEST_REDIS_DSN"',
            "reports:",
            "  junit_xml: true",
            "  html: false",
            "  allure: false",
            '  report_dir: "test_reports"',
            "",
        ]
    )


def _render_pytest_script(plan: dict[str, Any], package_name: str) -> str:
    project_root = str(ROOT).replace("\\", "\\\\")
    return f'''from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(r"{project_root}")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from actions.case_binding import execute_case_binding

PACKAGE_NAME = "{package_name}"


def _requirement_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _load_cases():
    plan = _load_json(_requirement_root() / "outputs" / "test_execution_plan.json", {{"cases": []}})
    return plan.get("cases", [])


CASES = _load_cases()


@pytest.fixture(scope="session")
def ai_test_env():
    requirement_root = _requirement_root()
    env_file = requirement_root / "env" / "test_env.yaml"
    return {{
        "requirement_root": requirement_root,
        "env_file": env_file,
        "env_text": env_file.read_text(encoding="utf-8") if env_file.exists() else "",
    }}


@pytest.mark.ai_generated
@pytest.mark.parametrize("case", CASES, ids=lambda item: item["case_id"])
def test_ai_generated_case_binding(case, ai_test_env):
    binding = case.get("binding", {{}})
    if binding.get("status") != "ready":
        pytest.skip(
            f"{{case['case_id']}} {{case['title']}} is not bound to executable API/page/fixture/DB code"
        )
    result = execute_case_binding(case, ai_test_env)
    assert result["status"] == "passed"
'''


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _write_artifacts(requirement_root: Path, package_name: str, plan: dict[str, Any]) -> dict[str, str]:
    outputs_root = requirement_root / "outputs"
    execution_dir = outputs_root / "test_execution"
    reports_dir = outputs_root / "test_reports"
    env_path = requirement_root / "env" / "test_env.yaml"
    data_path = requirement_root / "data" / "test_data.json"
    binding_path = requirement_root / "automation" / "bindings.json"
    binding_example_path = requirement_root / "automation" / "bindings.example.json"
    binding_template_path = requirement_root / "automation" / "bindings.generated.template.json"
    plan_path = execution_dir / "test_execution_plan.json"
    script_path = requirement_root / "tests" / "test_ai_generated_cases.py"
    junit_xml_path = reports_dir / "junit.xml"
    html_report_path = reports_dir / "pytest.html"
    allure_results_dir = reports_dir / "allure-results"

    _write_if_missing(env_path, _env_template(package_name))
    reports_dir.mkdir(parents=True, exist_ok=True)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(
        json.dumps(
            {
                "requirement": package_name,
                "note": "Generated from natural-language test cases. Replace placeholders with real isolated data.",
                "cases": [
                    {
                        "case_id": case["case_id"],
                        "priority": case["priority"],
                        "title": case["title"],
                        "test_data": case["test_data"],
                    }
                    for case in plan["cases"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_if_missing(
        binding_path,
        json.dumps({"cases": []}, ensure_ascii=False, indent=2),
    )
    binding_example_path.parent.mkdir(parents=True, exist_ok=True)
    binding_example_path.write_text(
        json.dumps(_binding_examples(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    binding_template_path.parent.mkdir(parents=True, exist_ok=True)
    binding_template_path.write_text(
        json.dumps(_binding_template(plan), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_render_pytest_script(plan, package_name), encoding="utf-8")

    return {
        "env_profile": str(env_path),
        "test_data": str(data_path),
        "binding_overrides": str(binding_path),
        "binding_example": str(binding_example_path),
        "binding_template": str(binding_template_path),
        "execution_plan": str(plan_path),
        "pytest_script": str(script_path),
        "reports_dir": str(reports_dir),
        "junit_xml": str(junit_xml_path),
        "html_report": str(html_report_path),
        "allure_results": str(allure_results_dir),
    }


def _binding_examples() -> dict[str, Any]:
    return {
        "cases": [
            {
                "case_id": "REQ-001",
                "binding": {
                    "status": "ready",
                    "type": "api",
                    "profile": "platform_admin",
                    "method": "POST",
                    "path": "/api/path",
                    "json": {},
                    "expected_status": 200,
                },
            },
            {
                "case_id": "REQ-002",
                "binding": {
                    "status": "ready",
                    "type": "api_flow",
                    "profile": "platform_admin",
                    "steps": [
                        {
                            "name": "create_data",
                            "method": "POST",
                            "path": "/api/test-data",
                            "json": {"scene": "replace_me"},
                            "expected_status": 200,
                            "assertions": [{"type": "json_equals", "path": "$.success", "expected": True}],
                        },
                        {
                            "name": "execute_business_action",
                            "method": "POST",
                            "path": "/api/business-action",
                            "json": {"id": "{{create_data.json.data.id}}"},
                            "expected_status": 200,
                        },
                    ],
                    "cleanup": [
                        {
                            "name": "delete_data",
                            "method": "DELETE",
                            "path": "/api/test-data/{{create_data.json.data.id}}",
                            "expected_status": 200,
                        }
                    ],
                },
            },
            {
                "case_id": "REQ-003",
                "binding": {
                    "status": "ready",
                    "type": "db_assert",
                    "engine": "postgres",
                    "dsn_env": "TEST_PG_DSN",
                    "assertions": [
                        {
                            "query": "select count(*) from table_name where id = %s",
                            "params": ["replace_me"],
                            "expected_first_value": 1,
                        }
                    ],
                },
            },
            {
                "case_id": "REQ-004",
                "binding": {
                    "status": "ready",
                    "type": "scenario",
                    "profile": "platform_admin",
                    "data": {
                        "merchant_id": "replace_me",
                        "deposit_amount": 1000,
                        "voucher_file_id": "replace_me",
                    },
                    "generators": {
                        "request_no": {"type": "sequence", "prefix": "DEP"},
                        "scene_id": {"type": "short_uuid", "length": 10},
                    },
                    "steps": [
                        {
                            "name": "submit_deposit",
                            "method": "POST",
                            "path": "/deposit/payment/submit",
                            "json": {
                                "requestNo": "{{gen.request_no}}",
                                "merchantId": "{{data.merchant_id}}",
                                "amount": "{{data.deposit_amount}}",
                                "voucherFileId": "{{data.voucher_file_id}}",
                            },
                            "expected_status": 200,
                            "assertions": [{"type": "json_equals", "path": "$.success", "expected": True}],
                        },
                        {
                            "name": "approve_deposit",
                            "method": "POST",
                            "path": "/deposit/payment/{{submit_deposit.json.data.applyId}}/approve",
                            "json": {"auditResult": "APPROVED"},
                            "expected_status": 200,
                        },
                    ],
                    "db_assertions": [
                        {
                            "query": "select status from deposit_payment where request_no = %s",
                            "params": ["{{gen.request_no}}"],
                            "expected_first_value": "APPROVED",
                        }
                    ],
                    "cleanup": [
                        {
                            "name": "cleanup_scene",
                            "method": "DELETE",
                            "path": "/test-support/deposit/{{gen.scene_id}}",
                            "expected_status": 200,
                        }
                    ],
                },
            },
        ]
    }


def _binding_template(plan: dict[str, Any]) -> dict[str, Any]:
    templates: list[dict[str, Any]] = []
    for case in plan.get("cases", []):
        if case.get("binding", {}).get("status") == "ready":
            continue
        if str(case.get("priority")) != "P0":
            continue
        templates.append(
            {
                "case_id": case.get("case_id"),
                "title": case.get("title"),
                "binding": _suggest_binding(case),
            }
        )
    return {
        "note": "Copy needed cases into automation/bindings.json, fill paths/data/assertions, then rerun the workflow.",
        "cases": templates,
    }


def _suggest_binding(case: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("case_id", ""))
    if case_id in {"DEP-P0-004", "DEP-P0-005", "DEP-P0-006", "DEP-P0-012", "DEP-P0-014", "DEP-P0-019"}:
        return {
            "status": "draft",
            "type": "scenario",
            "profile": "platform_admin",
            "data": {
                "merchant_id": "replace_me",
                "deposit_amount": 1000,
                "voucher_file_id": "replace_me",
                "operator_id": "replace_me",
            },
            "generators": {
                "request_no": {"type": "sequence", "prefix": "DEP"},
                "scene_id": {"type": "short_uuid", "length": 10},
            },
            "steps": [
                {
                    "name": "prepare_data",
                    "method": "POST",
                    "path": "/test-support/deposit/prepare",
                    "json": {
                        "case_id": case_id,
                        "sceneId": "{{gen.scene_id}}",
                        "merchantId": "{{data.merchant_id}}",
                    },
                    "expected_status": 200,
                    "assertions": [{"type": "json_equals", "path": "$.success", "expected": True}],
                },
                {
                    "name": "execute_action",
                    "method": "POST",
                    "path": "/deposit/action/replace-me",
                    "json": {
                        "requestNo": "{{gen.request_no}}",
                        "merchantId": "{{prepare_data.json.data.merchant_id}}",
                        "amount": "{{data.deposit_amount}}",
                    },
                    "expected_status": 200,
                    "assertions": [{"type": "json_equals", "path": "$.success", "expected": True}],
                },
            ],
            "db_assertions": [
                {
                    "query": "select count(*) from replace_table where request_no = %s",
                    "params": ["{{gen.request_no}}"],
                    "expected_first_value": 1,
                }
            ],
            "cleanup": [
                {
                    "name": "cleanup_data",
                    "method": "DELETE",
                    "path": "/test-support/deposit/{{gen.scene_id}}",
                    "expected_status": 200,
                }
            ],
        }
    if case_id in {"DEP-P0-001", "DEP-P0-009", "DEP-P0-018"}:
        return {
            "status": "draft",
            "type": "api",
            "profile": "platform_admin",
            "method": "POST",
            "path": "/deposit/permission-or-validation/replace-me",
            "json": {"case_id": case_id, "merchant_id": "replace_me"},
            "expected_status": 403 if case_id in {"DEP-P0-001", "DEP-P0-018"} else 400,
            "assertions": [{"type": "body_contains", "expected": "replace_with_error_message"}],
        }
    if case_id in {"DEP-P0-011", "DEP-P0-013", "DEP-P0-016", "DEP-P0-017"}:
        return {
            "status": "draft",
            "type": "scenario",
            "profile": "platform_admin",
            "data": {
                "merchant_id": "replace_me",
                "category_id": "replace_me",
                "deposit_amount": 1000,
                "operator_id": "replace_me",
            },
            "generators": {
                "request_no": {"type": "sequence", "prefix": "DEP"},
                "scene_id": {"type": "short_uuid", "length": 10},
            },
            "steps": [
                {
                    "name": "prepare_data",
                    "method": "POST",
                    "path": "/test-support/deposit/prepare",
                    "json": {
                        "case_id": case_id,
                        "sceneId": "{{gen.scene_id}}",
                        "merchantId": "{{data.merchant_id}}",
                        "categoryId": "{{data.category_id}}",
                    },
                    "expected_status": 200,
                },
                {
                    "name": "execute_business_flow",
                    "method": "POST",
                    "path": "/deposit/flow/replace-me",
                    "json": {
                        "requestNo": "{{gen.request_no}}",
                        "merchantId": "{{prepare_data.json.data.merchant_id}}",
                        "amount": "{{data.deposit_amount}}",
                    },
                    "expected_status": 200,
                },
            ],
            "db_assertions": [
                {
                    "query": "select count(*) from replace_table where request_no = %s",
                    "params": ["{{gen.request_no}}"],
                    "expected_first_value": 1,
                }
            ],
            "cleanup": [
                {
                    "name": "cleanup_data",
                    "method": "DELETE",
                    "path": "/test-support/deposit/{{gen.scene_id}}",
                    "expected_status": 200,
                }
            ],
        }
    return {
        "status": "draft",
        "type": "api",
        "profile": "platform_admin",
        "method": "GET",
        "path": "/replace-me",
        "expected_status": 200,
    }


def _relative_pytest_target(workspace_root: Path, requirement_root: Path) -> str:
    tests_dir = requirement_root / "tests"
    try:
        return tests_dir.relative_to(workspace_root).as_posix()
    except ValueError:
        return str(tests_dir)


def _extract_pytest_counts(summary: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for name in counts:
        match = re.search(rf"(\d+)\s+{name}", summary)
        if match:
            counts[name] = int(match.group(1))
    return counts


def _build_report_args(env_path: Path, artifacts: dict[str, str]) -> list[str]:
    if not env_path.exists():
        return []

    env_config = parse_env_text(env_path.read_text(encoding="utf-8"))
    reports = env_config.get("reports", {})
    if not isinstance(reports, dict):
        return []

    args: list[str] = []
    if reports.get("junit_xml", True):
        args.extend(["--junitxml", artifacts["junit_xml"]])
    if reports.get("html", False):
        args.extend(["--html", artifacts["html_report"], "--self-contained-html"])
    if reports.get("allure", False):
        Path(artifacts["allure_results"]).mkdir(parents=True, exist_ok=True)
        args.extend(["--alluredir", artifacts["allure_results"]])
    return args


def execute_test_workflow(
    user_text: str,
    requirement_context: dict[str, Any],
    workspace_root: str = "",
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    current_workspace = Path(workspace_root) if workspace_root else Path.cwd()
    requirement_root = _requirement_root(current_workspace, requirement_context)
    package_name = _package_name(requirement_root, requirement_context)

    cases_result = generate_test_cases(user_text, requirement_context)
    plan = _build_execution_plan(cases_result)
    plan = apply_auto_bindings(plan, _safe_slug(package_name))
    plan = merge_binding_overrides(plan, requirement_root / "automation" / "bindings.json")
    artifacts = _write_artifacts(requirement_root, _safe_slug(package_name), plan)

    pytest_target = _relative_pytest_target(current_workspace, requirement_root)
    execution_result = run_pytest(
        target=pytest_target,
        workspace_root=str(current_workspace),
        extra_args=_build_report_args(requirement_root / "env" / "test_env.yaml", artifacts),
        timeout_seconds=timeout_seconds,
    )
    raw_pytest_output = f"{execution_result.get('stdout', '')}\n{execution_result.get('stderr', '')}".strip()
    analysis_result = analyze_pytest_result(raw_pytest_output, execution_result=execution_result)
    pytest_counts = _extract_pytest_counts(str(analysis_result.get("pytest_summary", "")))

    blocked = plan["ready_count"] == 0
    return {
        "_ok": execution_result.get("exit_code") == 0,
        "_metadata": {
            "case_count": plan["case_count"],
            "ready_count": plan["ready_count"],
            "pending_count": plan["pending_count"],
            "pytest_exit_code": execution_result.get("exit_code"),
        },
        "task": "test_workflow_execution",
        "analysis_basis": cases_result.get("analysis_basis", {}),
        "case_count": plan["case_count"],
        "automation_ready_count": plan["ready_count"],
        "pending_binding_count": plan["pending_count"],
        "pytest_counts": pytest_counts,
        "blocked_by_environment": blocked,
        "artifacts": artifacts,
        "pytest_target": pytest_target,
        "stages": [
            {"name": "generate_test_cases", "status": "ok", "case_count": cases_result.get("case_count", 0)},
            {"name": "build_execution_plan", "status": "blocked" if blocked else "ok"},
            {"name": "prepare_test_data_and_env", "status": "ok"},
            {"name": "generate_pytest_contract", "status": "ok"},
            {"name": "run_pytest", "status": "ok" if execution_result.get("exit_code") == 0 else "failed"},
            {"name": "analyze_pytest_result", "status": "ok", "error_type": analysis_result.get("error_type")},
        ],
        "honest_conclusion": [
            f"已完成自然语言测试用例到 pytest 合约脚本的转换，并已执行 pytest；当前执行计划 ready={plan['ready_count']}，pending={plan['pending_count']}。",
            "ready case 会调用绑定执行器真实断言；pending case 不会伪装通过，会明确 skip 并提示缺少 API/page/fixture/DB binding。",
            "如果需求目录已有手写或已绑定 pytest 用例，它们会和 AI 生成的合约脚本一起执行。",
        ],
        "next_actions": [
            "补全 env/test_env.yaml 中的 base_url、api_base_url、账号、token 和依赖服务配置。",
            "在 automation/bindings.json 中为更多 case 补充 API/page/fixture/DB binding；重新执行后会合并到 test_execution_plan.json。",
            "把 pending case 逐步绑定到真实请求、页面操作、断言、数据准备和清理逻辑。",
            "需要报告能力时再接入 junitxml、pytest-html 或 Allure。",
        ],
        "cases_result": cases_result,
        "execution_plan": plan,
        "execution_result": execution_result,
        "analysis_result": analysis_result,
    }
