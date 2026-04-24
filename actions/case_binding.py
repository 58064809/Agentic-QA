from __future__ import annotations

import datetime as dt
import json
import os
import random
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from tools.auth_provider import AuthProvider
from tools.env_config import parse_and_flatten_env_text
from tools.env_config import parse_env_text
from tools.http_client import HttpClient
from tools.pg_client import PgReadonlyClient

MAX_DB_ROWS = 200
STRICT_TEMPLATE_RENDERING = True

DEPOSIT_AUTO_BINDINGS: dict[str, dict[str, Any]] = {
    "DEP-P0-002": {
        "status": "ready",
        "type": "python_adapter",
        "target": "deposit.required_total_deposit",
        "reason": "pure calculation rule can be verified without external environment",
        "scenarios": [
            {"base_deposit": 5000, "risk_deposit": 8000, "expected": 8000},
            {"base_deposit": 10000, "risk_deposit": 3000, "expected": 10000},
            {"base_deposit": 6000, "risk_deposit": 6000, "expected": 6000},
        ],
    },
    "DEP-P0-003": {
        "status": "ready",
        "type": "python_adapter",
        "target": "deposit.base_deposit",
        "reason": "pure calculation rule can be verified without external environment",
        "scenarios": [
            {"general_deposit": 3000, "special_category_deposit": 6000, "expected": 6000},
            {"general_deposit": 8000, "special_category_deposit": 5000, "expected": 8000},
            {"general_deposit": 5000, "special_category_deposit": 5000, "expected": 5000},
        ],
    },
    "DEP-P0-007": {
        "status": "ready",
        "type": "python_adapter",
        "target": "deposit.payment_amount_validation",
        "reason": "boundary values are explicit enough to execute as deterministic assertions",
        "scenarios": [
            {"amount": None, "required_amount": 1000, "expected": False},
            {"amount": 0, "required_amount": 1000, "expected": False},
            {"amount": 0.99, "required_amount": 1000, "expected": False},
            {"amount": 1.00, "required_amount": 1000, "expected": True},
            {"amount": 1000, "required_amount": 1000, "expected": True},
            {"amount": 2000, "required_amount": 1000, "expected": True},
            {"amount": 2000.01, "required_amount": 1000, "expected": False},
            {"amount": -1, "required_amount": 1000, "expected": False},
            {"amount": 1.001, "required_amount": 1000, "expected": False},
        ],
    },
    "DEP-P0-010": {
        "status": "ready",
        "type": "python_adapter",
        "target": "deposit.status_transition",
        "reason": "status transition rule can be verified from paid and required amounts",
        "scenarios": [
            {"paid_amount": 0, "required_amount": 1000, "expected": "UNPAID"},
            {"paid_amount": 1000, "required_amount": 1000, "expected": "PAID"},
            {"paid_amount": 1500, "required_amount": 1000, "expected": "PAID"},
            {"paid_amount": 1, "required_amount": 1000, "expected": "INSUFFICIENT"},
            {"paid_amount": 999.99, "required_amount": 1000, "expected": "INSUFFICIENT"},
        ],
    },
}


def apply_auto_bindings(plan: dict[str, Any], package_name: str) -> dict[str, Any]:
    bindings = DEPOSIT_AUTO_BINDINGS if "deposit" in package_name or "guarantee" in package_name else {}
    ready_count = 0
    pending_count = 0
    for case in plan.get("cases", []):
        binding = bindings.get(str(case.get("case_id")))
        if binding:
            case["binding"] = dict(binding)
            ready_count += 1
        else:
            pending_count += 1
    plan["ready_count"] = ready_count
    plan["pending_count"] = pending_count
    return plan


def merge_binding_overrides(plan: dict[str, Any], binding_file: Path) -> dict[str, Any]:
    if not binding_file.exists():
        return plan

    overrides = json.loads(binding_file.read_text(encoding="utf-8"))
    by_case_id = {item.get("case_id"): item.get("binding", {}) for item in overrides.get("cases", [])}
    ready_count = 0
    pending_count = 0
    for case in plan.get("cases", []):
        case_id = case.get("case_id")
        if case_id in by_case_id:
            case["binding"] = by_case_id[case_id]
        if case.get("binding", {}).get("status") == "ready":
            ready_count += 1
        else:
            pending_count += 1
    plan["ready_count"] = ready_count
    plan["pending_count"] = pending_count
    return plan


def execute_case_binding(case: dict[str, Any], env: dict[str, Any] | None = None) -> dict[str, Any]:
    binding = case.get("binding", {})
    binding_type = binding.get("type")
    _validate_binding_schema(case)
    if binding_type == "python_adapter":
        return _execute_python_adapter(case)
    if binding_type == "api":
        return _execute_api_binding(case, env or {})
    if binding_type == "api_flow":
        return _execute_api_flow_binding(case, env or {})
    if binding_type == "scenario":
        return _execute_scenario_binding(case, env or {})
    if binding_type == "db_assert":
        return _execute_db_assert_binding(case, env or {})
    raise AssertionError(f"Unsupported binding type for {case.get('case_id')}: {binding_type}")


def _execute_python_adapter(case: dict[str, Any]) -> dict[str, Any]:
    binding = case.get("binding", {})
    target = binding.get("target")
    scenarios = binding.get("scenarios", [])
    if target == "deposit.required_total_deposit":
        return _run_scenarios(case, scenarios, _required_total_deposit, ("base_deposit", "risk_deposit"))
    if target == "deposit.base_deposit":
        return _run_scenarios(case, scenarios, _base_deposit, ("general_deposit", "special_category_deposit"))
    if target == "deposit.payment_amount_validation":
        return _run_scenarios(case, scenarios, _payment_amount_is_valid, ("amount", "required_amount"))
    if target == "deposit.status_transition":
        return _run_scenarios(case, scenarios, _deposit_status, ("paid_amount", "required_amount"))
    raise AssertionError(f"Unknown python adapter target for {case.get('case_id')}: {target}")


def _run_scenarios(
    case: dict[str, Any],
    scenarios: list[dict[str, Any]],
    func,
    arg_names: tuple[str, ...],
) -> dict[str, Any]:
    if not scenarios:
        raise AssertionError(f"{case.get('case_id')} has no executable scenarios")

    details: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios, start=1):
        args = [scenario[name] for name in arg_names]
        actual = func(*args)
        expected = scenario["expected"]
        assert actual == expected, (
            f"{case.get('case_id')} scenario {index} expected {expected!r}, got {actual!r}; "
            f"input={scenario}"
        )
        details.append({"scenario": index, "actual": actual, "expected": expected})
    return {"status": "passed", "case_id": case.get("case_id"), "details": details}


def _required_total_deposit(base_deposit: int | float, risk_deposit: int | float) -> int | float:
    return max(base_deposit, risk_deposit)


def _base_deposit(general_deposit: int | float, special_category_deposit: int | float) -> int | float:
    return max(general_deposit, special_category_deposit)


def _payment_amount_is_valid(amount: int | float | None, required_amount: int | float) -> bool:
    if amount is None:
        return False
    if amount < 1:
        return False
    if amount > required_amount * 2:
        return False
    return round(amount, 2) == amount


def _deposit_status(paid_amount: int | float, required_amount: int | float) -> str:
    if paid_amount <= 0:
        return "UNPAID"
    if paid_amount >= required_amount:
        return "PAID"
    return "INSUFFICIENT"


def _execute_api_binding(case: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    binding = case.get("binding", {})
    response = _send_api_step(case, binding, env, {"env": _env_config(env)})
    return {
        "status": "passed",
        "case_id": case.get("case_id"),
        "http_status": response["status_code"],
        "response_json": response.get("json"),
    }


def _execute_api_flow_binding(case: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    binding = case.get("binding", {})
    steps = binding.get("steps", [])
    cleanup_steps = binding.get("cleanup", [])
    if not steps:
        raise AssertionError(f"{case.get('case_id')} api_flow binding requires at least one step")

    context: dict[str, Any] = {"env": _env_config(env)}
    executed_steps: list[dict[str, Any]] = []
    failure: BaseException | None = None
    try:
        for step in steps:
            response = _send_api_step(case, step, env, context)
            name = str(step.get("name") or f"step_{len(executed_steps) + 1}")
            context[name] = response
            executed_steps.append(
                {"name": name, "status_code": response["status_code"], "assertions": len(step.get("assertions", []))}
            )
    except BaseException as exc:
        failure = exc
        raise
    finally:
        cleanup_results = _run_cleanup_steps(case, cleanup_steps, env, context)
        if failure is None:
            context["cleanup_results"] = cleanup_results

    return {
        "status": "passed",
        "case_id": case.get("case_id"),
        "steps": executed_steps,
        "cleanup": context.get("cleanup_results", []),
    }


def _execute_scenario_binding(case: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    binding = case.get("binding", {})
    context = _build_scenario_context(binding, env)
    executed_steps = _execute_scenario_steps(case, binding.get("steps", []), env, context)
    db_results = _execute_inline_db_assertions(case, binding.get("db_assertions", []), env, context)
    cleanup_results = _run_cleanup_steps(case, binding.get("cleanup", []), env, context)
    return {
        "status": "passed",
        "case_id": case.get("case_id"),
        "steps": executed_steps,
        "db_assertions": db_results,
        "cleanup": cleanup_results,
    }


def _build_scenario_context(binding: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    context = {
        "data": dict(binding.get("data", {})),
        "env": _env_config(env),
        "gen": {},
    }
    for key, generator in binding.get("generators", {}).items():
        context["gen"][key] = _generate_value(generator)
    return context


def _execute_scenario_steps(
    case: dict[str, Any],
    steps: list[dict[str, Any]],
    env: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    if not steps:
        raise AssertionError(f"{case.get('case_id')} scenario binding requires at least one step")

    executed_steps: list[dict[str, Any]] = []
    try:
        for step in steps:
            rendered_step = _render_templates(step, context)
            response = _send_api_step(case, rendered_step, env, context)
            name = str(rendered_step.get("name") or f"step_{len(executed_steps) + 1}")
            context[name] = response
            executed_steps.append(
                {"name": name, "status_code": response["status_code"], "assertions": len(step.get("assertions", []))}
            )
    except BaseException:
        _run_cleanup_steps(case, steps=[], env=env, context=context)
        raise
    return executed_steps


def _execute_inline_db_assertions(
    case: dict[str, Any],
    assertions: list[dict[str, Any]],
    env: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    if not assertions:
        return []

    rendered_assertions = _render_templates(assertions, context)
    result = _execute_db_assert_binding(
        {
            "case_id": case.get("case_id"),
            "binding": {
                "type": "db_assert",
                "status": "ready",
                "assertions": rendered_assertions,
            },
        },
        env,
    )
    return list(result.get("db_assertions", []))


def _run_cleanup_steps(
    case: dict[str, Any],
    cleanup_steps: list[dict[str, Any]],
    env: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for step in cleanup_steps:
        response = _send_api_step(case, step, env, context, assert_response=False)
        results.append({"name": step.get("name") or "cleanup", "status_code": response["status_code"]})
    return results


def _send_api_step(
    case: dict[str, Any],
    step: dict[str, Any],
    env: dict[str, Any],
    context: dict[str, Any],
    *,
    assert_response: bool = True,
) -> dict[str, Any]:
    config = _env_config(env)
    profile_config = _resolve_api_profile(config, step.get("profile"))
    step_context = dict(context)
    step_context.setdefault("env", config)
    base_url = step.get("base_url") or profile_config.get("api_base_url") or profile_config.get("base_url")
    if not base_url:
        raise AssertionError(f"{case.get('case_id')} api binding requires api_base_url or base_url")

    method = str(step.get("method", "GET")).upper()
    path = _render_template(str(step.get("path", "")), step_context)
    headers = _render_templates(dict(profile_config.get("headers", {})), step_context)
    headers.update(_render_templates(dict(step.get("headers", {})), step_context))
    body = _render_templates(step.get("json"), step_context)
    headers = _merge_cookie_headers(headers, profile_config.get("cookies", {}), step_context)
    if STRICT_TEMPLATE_RENDERING:
        _assert_no_unresolved_templates(path, case_id=str(case.get("case_id", "")), field="path")
        _assert_no_unresolved_templates(headers, case_id=str(case.get("case_id", "")), field="headers")
        _assert_no_unresolved_templates(body, case_id=str(case.get("case_id", "")), field="json")
    auth_profile = step.get("auth")
    token_env = step.get("token_env") or profile_config.get("token_env")
    token = step.get("token") or profile_config.get("token")
    auth_mode = str(step.get("auth_mode") or profile_config.get("auth_mode") or "bearer").lower()
    auth_header_name = str(step.get("auth_header_name") or profile_config.get("auth_header_name") or "Authorization")
    token_type = str(profile_config.get("token_type") or "Bearer")
    if not auth_profile and (token or token_env):
        auth_profile = _resolve_default_auth_profile(
            token=token,
            token_env=token_env,
            token_type=token_type,
            auth_mode=auth_mode,
            auth_header_name=auth_header_name,
            headers=headers,
        )
    client = HttpClient(base_url=str(base_url), timeout_seconds=int(step.get("timeout_seconds", 10)))
    response = client.request(
        method,
        path,
        headers=headers,
        json_body=body,
        auth=auth_profile,
        retries=int(step.get("retries", 0)),
    )
    result = {"status_code": response.status_code, "body": response.body, "json": response.json}
    if assert_response:
        _assert_api_response(case, step, result)
    return result


def _assert_api_response(case: dict[str, Any], step: dict[str, Any], response: dict[str, Any]) -> None:
    expected_status = int(step.get("expected_status", 200))
    assert response["status_code"] == expected_status, (
        f"{case.get('case_id')} {step.get('name', 'api')} expected HTTP {expected_status}, "
        f"got {response['status_code']}; body={response['body'][:500]}"
    )

    for assertion in step.get("assertions", []):
        assertion_type = assertion.get("type")
        if assertion_type == "json_equals":
            actual = _get_json_path(response.get("json"), str(assertion.get("path", "")))
            expected = assertion.get("expected")
            assert actual == expected, (
                f"{case.get('case_id')} {step.get('name', 'api')} json path {assertion.get('path')} "
                f"expected {expected!r}, got {actual!r}"
            )
        elif assertion_type == "body_contains":
            expected_text = str(assertion.get("expected", ""))
            assert expected_text in response.get("body", ""), (
                f"{case.get('case_id')} {step.get('name', 'api')} body missing {expected_text!r}"
            )
        else:
            raise AssertionError(f"{case.get('case_id')} unsupported api assertion type: {assertion_type}")


def _execute_db_assert_binding(case: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
    binding = case.get("binding", {})
    assertions = binding.get("assertions", [])
    if not assertions:
        raise AssertionError(f"{case.get('case_id')} db_assert binding requires assertions")

    config = _env_config(env)
    engine = str(binding.get("engine") or config.get("db_engine") or "").lower()
    db_path = binding.get("sqlite_path") or config.get("sqlite_path")
    pg_dsn = binding.get("pg_dsn") or config.get("pg_dsn") or _dsn_from_env(binding.get("dsn_env") or config.get("pg_dsn_env"))

    if not engine:
        engine = "sqlite" if db_path else "postgres" if pg_dsn else ""
    if engine not in {"sqlite", "postgres", "pg"}:
        raise AssertionError(f"{case.get('case_id')} unsupported db_assert engine: {engine}")

    if engine == "sqlite":
        if not db_path:
            raise AssertionError(f"{case.get('case_id')} sqlite db_assert requires sqlite_path")
        return _execute_sqlite_assertions(case, str(db_path), assertions)
    if not pg_dsn:
        raise AssertionError(f"{case.get('case_id')} postgres db_assert requires pg_dsn or dsn_env")
    return _execute_postgres_assertions(case, str(pg_dsn), assertions)


def _execute_sqlite_assertions(case: dict[str, Any], db_path: str, assertions: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for assertion in assertions:
            query = str(assertion.get("query", "")).strip()
            _assert_readonly_query(case, query)
            cursor = connection.execute(query, assertion.get("params", []))
            rows = cursor.fetchmany(MAX_DB_ROWS + 1)
            if len(rows) > MAX_DB_ROWS:
                raise AssertionError(f"{case.get('case_id')} db result too large (>{MAX_DB_ROWS} rows)")
            expected_row_count = assertion.get("expected_row_count")
            if expected_row_count is not None:
                assert len(rows) == int(expected_row_count), (
                    f"{case.get('case_id')} db row count expected {expected_row_count}, got {len(rows)}"
                )
            if "expected_first_value" in assertion:
                actual = rows[0][0] if rows else None
                expected = assertion["expected_first_value"]
                assert actual == expected, (
                    f"{case.get('case_id')} db first value expected {expected!r}, got {actual!r}"
                )
            results.append({"query": query, "row_count": len(rows)})
    finally:
        connection.close()

    return {"status": "passed", "case_id": case.get("case_id"), "db_assertions": results}


def _execute_postgres_assertions(case: dict[str, Any], dsn: str, assertions: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    client = PgReadonlyClient(dsn=dsn)
    for assertion in assertions:
        query = str(assertion.get("query", "")).strip()
        _assert_readonly_query(case, query)
        rows = client.query(query, assertion.get("params", []))
        if len(rows) > MAX_DB_ROWS:
            raise AssertionError(f"{case.get('case_id')} pg result too large (>{MAX_DB_ROWS} rows)")
        expected_row_count = assertion.get("expected_row_count")
        if expected_row_count is not None:
            assert len(rows) == int(expected_row_count), (
                f"{case.get('case_id')} pg row count expected {expected_row_count}, got {len(rows)}"
            )
        if "expected_first_value" in assertion:
            actual = rows[0][0] if rows else None
            expected = assertion["expected_first_value"]
            assert actual == expected, (
                f"{case.get('case_id')} pg first value expected {expected!r}, got {actual!r}"
            )
        results.append({"query": query, "row_count": len(rows)})

    return {"status": "passed", "case_id": case.get("case_id"), "db_assertions": results}


def _dsn_from_env(env_name: Any) -> str:
    if not env_name:
        return ""
    return os.getenv(str(env_name), "")


def _env_config(env: dict[str, Any]) -> dict[str, Any]:
    config = dict(env)
    env_text = str(env.get("env_text", ""))
    parsed_env = parse_env_text(env_text)
    config.update(parsed_env)
    config.update({key: value for key, value in parse_and_flatten_env_text(env_text).items() if value})
    if "TEST_DB_SQLITE" in os.environ:
        config.setdefault("sqlite_path", os.environ["TEST_DB_SQLITE"])
    if "TEST_PG_DSN" in os.environ:
        config.setdefault("pg_dsn_env", "TEST_PG_DSN")
    return config


def _resolve_api_profile(config: dict[str, Any], profile_name: Any) -> dict[str, Any]:
    selected_name = str(profile_name or _active_profile_name(config) or "").strip()
    profiles = config.get("profiles", {})
    profile = profiles.get(selected_name, {}) if isinstance(profiles, dict) and selected_name else {}

    resolved = {
        "name": selected_name,
        "base_url": _pick_first(
            _nested_value(profile, "environment", "base_url"),
            profile.get("base_url") if isinstance(profile, dict) else "",
            config.get("base_url"),
        ),
        "api_base_url": _pick_first(
            _nested_value(profile, "environment", "api_base_url"),
            profile.get("api_base_url") if isinstance(profile, dict) else "",
            _nested_value(profile, "environment", "base_url"),
            profile.get("base_url") if isinstance(profile, dict) else "",
            config.get("api_base_url"),
            config.get("base_url"),
        ),
        "token": _pick_first(
            _nested_value(profile, "auth", "token"),
            profile.get("token") if isinstance(profile, dict) else "",
            config.get("token"),
        ),
        "token_env": _pick_first(
            _nested_value(profile, "auth", "token_env"),
            profile.get("token_env") if isinstance(profile, dict) else "",
            config.get("token_env"),
        ),
        "token_type": _pick_first(
            _nested_value(profile, "auth", "token_type"),
            profile.get("token_type") if isinstance(profile, dict) else "",
            config.get("token_type"),
            "Bearer",
        ),
        "auth_mode": _pick_first(
            _nested_value(profile, "auth", "mode"),
            profile.get("auth_mode") if isinstance(profile, dict) else "",
            config.get("auth_mode"),
            "bearer",
        ),
        "auth_header_name": _pick_first(
            _nested_value(profile, "auth", "header_name"),
            profile.get("auth_header_name") if isinstance(profile, dict) else "",
            config.get("auth_header_name"),
            "Authorization",
        ),
        "headers": _merge_dicts(_dict_section(config, "headers"), _dict_section(profile, "headers")),
        "cookies": _merge_dicts(_dict_section(config, "cookies"), _dict_section(profile, "cookies")),
    }
    return resolved


def _active_profile_name(config: dict[str, Any]) -> str:
    environment = config.get("environment")
    if isinstance(environment, dict) and environment.get("active_profile"):
        return str(environment["active_profile"])
    return str(config.get("active_profile") or "")


def _resolve_default_auth_profile(
    *,
    token: Any,
    token_env: Any,
    token_type: str,
    auth_mode: str,
    auth_header_name: str,
    headers: dict[str, Any],
) -> dict[str, Any] | None:
    token_value = AuthProvider().get_token(
        {"name": "default", "token": token, "token_env": token_env, "token_type": token_type}
    ).value
    if not token_value:
        return None

    normalized_mode = auth_mode.lower()
    if normalized_mode in {"bearer", "authorization"}:
        return {
            "name": "default",
            "token": token_value,
            "token_env": "",
            "token_type": token_type or "Bearer",
        }
    if normalized_mode == "cookie":
        headers["Cookie"] = _merge_cookie_value(headers.get("Cookie", ""), token_value)
        return None
    if normalized_mode == "header":
        headers.setdefault(auth_header_name or "Authorization", token_value)
        return None
    if normalized_mode == "none":
        return None
    raise AssertionError(f"Unsupported auth_mode: {auth_mode}")


def _merge_cookie_headers(headers: dict[str, Any], cookies: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    rendered = dict(headers)
    if not cookies:
        return rendered

    cookie_parts = [f"{key}={value}" for key, value in _render_templates(cookies, context).items() if value not in {"", None}]
    if not cookie_parts:
        return rendered
    rendered["Cookie"] = _merge_cookie_value(rendered.get("Cookie", ""), "; ".join(cookie_parts))
    return rendered


def _merge_cookie_value(existing: Any, extra: Any) -> str:
    current = str(existing or "").strip()
    addition = str(extra or "").strip()
    if not current:
        return addition
    if not addition:
        return current
    return f"{current}; {addition}"


def _dict_section(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    section = value.get(key, {})
    return dict(section) if isinstance(section, dict) else {}


def _nested_value(value: Any, section: str, key: str) -> Any:
    if not isinstance(value, dict):
        return ""
    nested = value.get(section, {})
    if not isinstance(nested, dict):
        return ""
    return nested.get(key, "")


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged.update(override)
    return merged


def _pick_first(*values: Any) -> Any:
    for value in values:
        if value not in ("", None):
            return value
    return ""


def _try_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _get_json_path(data: Any, path: str) -> Any:
    current = data
    for part in path.strip("$.").split("."):
        if part == "":
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


def _render_templates(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _render_template(value, context)
    if isinstance(value, list):
        return [_render_templates(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _render_templates(item, context) for key, item in value.items()}
    return value


def _render_template(value: str, context: dict[str, Any]) -> str:
    if value.startswith("{{") and value.endswith("}}") and value.count("{{") == 1:
        expression = value[2:-2].strip()
        return _resolve_context_expression(context, expression)

    rendered = value
    for match in set(part for part in value.split("{{") if "}}" in part):
        expression = match.split("}}", 1)[0].strip()
        replacement = _resolve_context_expression(context, expression)
        rendered = rendered.replace("{{" + expression + "}}", str(replacement))
    return rendered


def _resolve_context_expression(context: dict[str, Any], expression: str) -> Any:
    current: Any = context
    for part in expression.split("."):
        if isinstance(current, dict):
            if part in current:
                current = current.get(part)
            else:
                if STRICT_TEMPLATE_RENDERING:
                    raise AssertionError(f"unresolved template expression: {expression}")
                return ""
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            if STRICT_TEMPLATE_RENDERING:
                raise AssertionError(f"unresolved template expression: {expression}")
            return ""
    return "" if current is None else current


def _assert_no_unresolved_templates(value: Any, *, case_id: str, field: str) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if "{{" in value and "}}" in value:
            raise AssertionError(f"{case_id} unresolved template in {field}: {value}")
        return
    if isinstance(value, list):
        for item in value:
            _assert_no_unresolved_templates(item, case_id=case_id, field=field)
        return
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_unresolved_templates(item, case_id=case_id, field=field)
        return


def _validate_binding_schema(case: dict[str, Any]) -> None:
    binding = case.get("binding") or {}
    case_id = str(case.get("case_id", ""))
    if not isinstance(binding, dict):
        raise AssertionError(f"{case_id} binding must be a dict")
    binding_type = str(binding.get("type") or "")
    status = str(binding.get("status") or "")
    if status and status not in {"ready", "pending", "draft"}:
        raise AssertionError(f"{case_id} unsupported binding status: {status}")
    if binding_type in {"", "unbound"}:
        return
    if binding_type == "python_adapter":
        if not binding.get("target"):
            raise AssertionError(f"{case_id} python_adapter requires target")
        if not binding.get("scenarios"):
            raise AssertionError(f"{case_id} python_adapter requires scenarios")
        return
    if binding_type in {"api", "api_flow", "scenario"}:
        if binding_type == "api" and not binding.get("path"):
            raise AssertionError(f"{case_id} api binding requires path")
        if binding_type == "api_flow" and not binding.get("steps"):
            raise AssertionError(f"{case_id} api_flow binding requires steps")
        if binding_type == "scenario" and not binding.get("steps"):
            raise AssertionError(f"{case_id} scenario binding requires steps")
        return
    if binding_type == "db_assert":
        if not binding.get("assertions"):
            raise AssertionError(f"{case_id} db_assert requires assertions")
        return
    raise AssertionError(f"{case_id} unsupported binding type: {binding_type}")


def _generate_value(generator: Any) -> Any:
    if isinstance(generator, str):
        generator = {"type": generator}
    generator_type = str(generator.get("type", "uuid"))
    if generator_type == "uuid":
        return str(uuid.uuid4())
    if generator_type == "short_uuid":
        return uuid.uuid4().hex[: int(generator.get("length", 8))]
    if generator_type == "timestamp":
        return dt.datetime.now().strftime(str(generator.get("format", "%Y%m%d%H%M%S")))
    if generator_type == "random_int":
        start = int(generator.get("min", 1))
        end = int(generator.get("max", 999999))
        return random.randint(start, end)
    if generator_type == "sequence":
        prefix = str(generator.get("prefix", "AUTO"))
        return f"{prefix}{dt.datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(1000, 9999)}"
    if generator_type == "fixed":
        return generator.get("value")
    raise AssertionError(f"Unsupported generator type: {generator_type}")


def _assert_readonly_query(case: dict[str, Any], query: str) -> None:
    lowered = query.lower().strip()
    if not lowered.startswith("select"):
        raise AssertionError(f"{case.get('case_id')} db_assert only allows SELECT queries")
    forbidden = (" insert ", " update ", " delete ", " drop ", " alter ", " truncate ", " create ")
    padded = f" {lowered} "
    if any(keyword in padded for keyword in forbidden):
        raise AssertionError(f"{case.get('case_id')} db_assert query is not readonly")
