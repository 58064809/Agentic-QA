from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest
import yaml

from harness import (
    ApiScenarioPrepareCommand,
    ArtifactVariant,
    Harness,
    ReviewDecision,
    ReviewRunCommand,
    RunApiScenarioCommand,
    RunRef,
)
from harness.application.qa_design import TESTCASE_HEADERS
from harness.application.source import (
    SourceBundle,
    SourceCompleteness,
    SourceDocument,
    SourceIngestionLimits,
)
from harness.domain.schemas.api_test_cases import ApiTestCasesDraft
from harness.domain.schemas.openapi import OpenApiInspection
from harness.infrastructure.api_scenario_sources import (
    inspect_api_scenario_sources,
    validate_manual_case_mapping,
)
from harness.infrastructure.llm.gateway import CallableModelGateway
from harness.infrastructure.local_config import FilesystemLocalConfigLoader


def _sha(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _bundle(files: dict[str, str]) -> SourceBundle:
    documents = tuple(
        SourceDocument(
            path=path,
            raw_sha256=_sha(text),
            parsed_sha256=_sha(text),
            byte_size=len(text.encode()),
            text=text,
            completeness=SourceCompleteness.COMPLETE,
        )
        for path, text in files.items()
    )
    return SourceBundle(
        parser_version="test",
        limits=SourceIngestionLimits(),
        documents=documents,
        completeness=SourceCompleteness.COMPLETE,
        bundle_hash=_sha("".join(files.values())),
    )


def _openapi(*, external_ref: bool = False) -> str:
    schema = {"$ref": "schemas.yml#/Order"} if external_ref else {"type": "object"}
    return yaml.safe_dump(
        {
            "openapi": "3.0.3",
            "info": {"title": "Orders", "version": "1"},
            "paths": {
                "/orders": {
                    "post": {
                        "requestBody": {
                            "required": True,
                            "content": {"application/json": {"schema": schema}},
                        },
                        "responses": {"201": {"description": "created"}},
                    }
                }
            },
        },
        allow_unicode=True,
        sort_keys=False,
    )


def _row(case_id: str = "TC-ORDER-001") -> list[str]:
    return [
        case_id,
        "ORDER-001",
        "create order",
        "API",
        "P1",
        "QA environment is available",
        "sku=demo",
        "POST the order request",
        "HTTP status is 201",
        "status_code equals 201",
        "-",
    ]


def _csv(case_id: str = "TC-ORDER-001", *, bom: bool = False) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(TESTCASE_HEADERS)
    writer.writerow(_row(case_id))
    return ("\ufeff" if bom else "") + output.getvalue()


def _markdown() -> str:
    return "\n".join(
        [
            "# Manual cases",
            "",
            "| " + " | ".join(TESTCASE_HEADERS) + " |",
            "|" + "|".join(["---"] * 11) + "|",
            "| " + " | ".join(_row()) + " |",
        ]
    )


def _testcase_yaml() -> str:
    return yaml.safe_dump(
        {
            "schema_version": "agentic-qa.test-case-set.v1",
            "cases": [
                {
                    "case_id": "TC-ORDER-001",
                    "rule_ids": ["ORDER-001"],
                    "title": "create order",
                    "test_type": "API",
                    "priority": "P1",
                    "preconditions": ["QA environment is available"],
                    "test_data": ["sku=demo"],
                    "steps": ["POST the order request"],
                    "expected_results": ["HTTP status is 201"],
                    "assertions": ["status_code equals 201"],
                }
            ],
            "coverage": [
                {
                    "rule_id": "ORDER-001",
                    "case_ids": ["TC-ORDER-001"],
                    "rationale": "manual source",
                }
            ],
        },
        allow_unicode=True,
        sort_keys=False,
    )


@pytest.mark.parametrize(
    ("path", "manual"),
    [
        ("sources/cases.csv", _csv(bom=True)),
        ("sources/cases.md", _markdown()),
        ("sources/cases.yml", _testcase_yaml()),
    ],
)
def test_inspection_recognizes_supported_manual_formats(path: str, manual: str) -> None:
    inspection = inspect_api_scenario_sources(
        _bundle(
            {
                "sources/openapi.yml": _openapi(),
                path: manual,
                "sources/notes.txt": "ignored",
            }
        )
    )

    assert inspection.summary.manual_case_ids == ["TC-ORDER-001"]
    assert inspection.summary.manual_case_files[0].path == path
    assert inspection.summary.ignored_files[0].path == "sources/notes.txt"
    assert set(inspection.recognized_paths) == {"sources/openapi.yml", path}


def test_inspection_rejects_duplicate_case_ids_across_files() -> None:
    with pytest.raises(ValueError, match="globally unique"):
        inspect_api_scenario_sources(
            _bundle(
                {
                    "sources/openapi.yml": _openapi(),
                    "sources/a.csv": _csv(),
                    "sources/b.csv": _csv(),
                }
            )
        )


def test_inspection_rejects_bad_csv_and_external_openapi_refs() -> None:
    with pytest.raises(ValueError, match="exact ordered 11-column"):
        inspect_api_scenario_sources(
            _bundle({"sources/openapi.yml": _openapi(), "sources/cases.csv": "id,title\n1,x"})
        )
    with pytest.raises(ValueError, match="external OpenAPI reference"):
        inspect_api_scenario_sources(
            _bundle(
                {
                    "sources/openapi.yml": _openapi(external_ref=True),
                    "sources/cases.csv": _csv(),
                }
            )
        )


def test_inspection_requires_both_contract_and_manual_cases() -> None:
    with pytest.raises(ValueError, match="manual test-case"):
        inspect_api_scenario_sources(_bundle({"sources/openapi.yml": _openapi()}))
    with pytest.raises(ValueError, match="OpenAPI"):
        inspect_api_scenario_sources(_bundle({"sources/cases.csv": _csv()}))


def test_api_fast_reads_full_frozen_openapi_and_projects_model_context() -> None:
    payload = yaml.safe_load(_openapi())
    payload["paths"].update(
        {
            f"/catalog/{index}": {
                "get": {
                    "summary": f"catalog {index}",
                    "responses": {"200": {"description": "ok"}},
                }
            }
            for index in range(600)
        }
    )
    openapi_text = json.dumps(payload, ensure_ascii=False)
    manual_text = _csv().replace("POST the order request", "POST /orders")
    texts = {
        "sources/openapi.json": openapi_text,
        "sources/cases.csv": manual_text,
    }
    bundle = SourceBundle(
        parser_version="test",
        limits=SourceIngestionLimits(),
        documents=(
            SourceDocument(
                path="sources/openapi.json",
                raw_sha256=_sha(openapi_text),
                parsed_sha256=_sha(openapi_text[:100_000]),
                byte_size=len(openapi_text.encode()),
                text=openapi_text[:100_000],
                completeness=SourceCompleteness.PARTIAL,
                truncated=True,
            ),
            SourceDocument(
                path="sources/cases.csv",
                raw_sha256=_sha(manual_text),
                parsed_sha256=_sha(manual_text),
                byte_size=len(manual_text.encode()),
                text=manual_text,
                completeness=SourceCompleteness.COMPLETE,
            ),
        ),
        completeness=SourceCompleteness.PARTIAL,
        bundle_hash=_sha(openapi_text + manual_text),
    )

    inspection = inspect_api_scenario_sources(
        bundle,
        full_text_loader=lambda path: texts[path],
    )
    projected = inspection.model_tool_results()[0]["result"]
    projected_by_path = {endpoint["path"]: endpoint for endpoint in projected["endpoints"]}

    assert inspection.openapi[0].endpoint_count == 601
    assert len(projected["endpoints"]) == 601
    assert projected_by_path["/orders"]["responses"]
    assert projected_by_path["/catalog/599"]["responses"] == []
    OpenApiInspection.model_validate(projected)


def test_manual_mapping_requires_every_case_id() -> None:
    inspection = inspect_api_scenario_sources(
        _bundle({"sources/openapi.yml": _openapi(), "sources/cases.csv": _csv()})
    )
    draft = ApiTestCasesDraft.model_validate(
        {
            "schema_version": "agentic-qa.api-cases.v1.2",
            "artifact_type": "api_automation_cases",
            "status": "needs_human_review",
            "human_review_required": True,
            "business_rules": ["ORDER-001"],
            "source_refs": [
                {
                    "source_type": "openapi",
                    "source_path": "sources/openapi.yml",
                    "chunk_id": "POST /orders",
                    "locator": "POST /orders",
                    "summary": "create order",
                    "confidence": "high",
                }
            ],
            "cases": [
                {
                    "id": "api-order-pending",
                    "title": "pending mapping",
                    "priority": "P1",
                    "contract_status": "pending_confirmation",
                    "business_rule_refs": ["ORDER-001"],
                    "review_status": "needs_human_review",
                    "review_questions": ["Confirm endpoint"],
                    "source_refs": [
                        {
                            "source_type": "openapi",
                            "source_path": "sources/openapi.yml",
                            "chunk_id": "POST /orders",
                            "locator": "POST /orders",
                            "summary": "create order",
                            "confidence": "high",
                        }
                    ],
                    "pending": ["Endpoint is not confirmed"],
                    "request": {"method": None, "path": None},
                    "assertions": [],
                    "variables": {},
                    "cleanup": [],
                }
            ],
            "review_questions": ["Review mappings"],
        }
    )

    with pytest.raises(ValueError, match="do not map all"):
        validate_manual_case_mapping(draft, inspection)


def test_prepare_review_and_run_vertical_loop_uses_one_api_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    source_dir = repo / "local-sources" / "api" / "orders"
    source_dir.mkdir(parents=True)
    (source_dir / "openapi.yml").write_text(_openapi(), encoding="utf-8")
    (source_dir / "cases.csv").write_text(_csv(), encoding="utf-8")
    (source_dir / "notes.txt").write_text("must remain ignored", encoding="utf-8")
    (repo / "agentic-qa.local.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "agentic-qa.local-config.v2",
                "model": {
                    "provider": "recorded",
                    "api_key_env": "UNIT_MODEL_KEY",
                    "flash_model": "recorded-flash",
                    "pro_model": "recorded-pro",
                    "base_url": "https://model.example.test",
                },
                "rag": {},
                "system_database": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "postgres",
                    "user": "postgres",
                    "password": "unit-only",
                },
                "test_management": {"provider": "none"},
                "workspace_defaults": {},
                "api": {
                    "services": {
                        "orders": {
                            "source_directory": "local-sources/api/orders",
                            "environments": {
                                "qa": {
                                    "base_url": "https://qa.example.test",
                                    "trusted_origins": ["https://qa.example.test"],
                                    "allowed_http_methods": ["GET", "POST"],
                                    "cleanup_exempt_operations": ["POST /orders"],
                                    "auth": {"fallback_token": "fixture-runtime-token"},
                                }
                            },
                        }
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    FilesystemLocalConfigLoader(repo).migrate_inline_secrets()
    planner_calls = 0
    agent_calls = 0

    def respond(*, prompt: str, response_model: type, **_kwargs: object) -> object:
        nonlocal planner_calls, agent_calls
        if response_model.__name__ == "QAPlan":
            planner_calls += 1
            raise AssertionError("api_fast must not call the model planner")
        agent_calls += 1
        envelope = json.loads(prompt)
        context = {
            **envelope.get("trusted_context", {}),
            **envelope.get("untrusted_context", {}),
        }
        assert "notes.txt" not in prompt
        results = context["tool_results"]
        assert all(item["tool"] != "workspace.read" for item in results)
        openapi_result = next(
            item["result"] for item in results if item["tool"] == "openapi.inspect"
        )
        manual_result = next(
            item["result"] for item in results if item["tool"] == "manual-test-cases.inspect"
        )
        openapi_path = openapi_result["source"]
        manual_path = manual_result["cases"][0]["source_path"]
        openapi_ref = {
            "source_type": "openapi",
            "source_path": openapi_path,
            "chunk_id": "POST /orders",
            "locator": "POST /orders",
            "summary": "create order",
            "confidence": "high",
        }
        manual_ref = {
            "source_type": "manual-test-case",
            "source_path": manual_path,
            "chunk_id": "TC-ORDER-001",
            "locator": "case_id=TC-ORDER-001",
            "summary": "create order",
            "confidence": "high",
        }
        return {
            "summary": "assembled manual API scenario",
            "artifacts": {},
            "api_test_cases": {
                "schema_version": "agentic-qa.api-cases.v1.2",
                "artifact_type": "api_automation_cases",
                "status": "needs_human_review",
                "human_review_required": True,
                "business_rules": ["ORDER-001"],
                "source_refs": [openapi_ref, manual_ref],
                "cases": [
                    {
                        "id": "api-order-create",
                        "title": "create order",
                        "priority": "P1",
                        "contract_status": "confirmed",
                        "business_rule_refs": ["ORDER-001"],
                        "review_status": "needs_human_review",
                        "review_questions": ["Review test data"],
                        "source_refs": [openapi_ref, manual_ref],
                        "pending": [],
                        "request": {"method": "POST", "path": "/orders", "body": {}},
                        "assertions": [{"type": "status_code", "expected": 201}],
                        "variables": {"datasets": [], "extract": {}},
                        "cleanup": [],
                    }
                ],
                "review_questions": ["Review before publication"],
            },
            "evidence": [openapi_path, manual_path],
            "pending": [],
            "tool_requests": [],
        }

    harness = Harness(
        repo,
        model_gateway=CallableModelGateway(respond),
        allowed_source_roots=[source_dir],
    )
    command = ApiScenarioPrepareCommand(
        source_directory=str(source_dir),
        goal="assemble order API scenarios",
        environment="qa",
    )
    result = harness.prepare_api_scenario(command)
    repeated = harness.prepare_api_scenario(command)

    assert result.status == "needs_human_review"
    assert result.next_action == "human_review_required"
    assert result.sources.manual_case_ids == ["TC-ORDER-001"]
    assert result.sources.ignored_files[0].path.endswith("notes.txt")
    assert result.candidate.candidate_path.endswith("api_test_draft/raw.yml")
    assert repeated.run_id == result.run_id
    assert planner_calls == 0
    assert agent_calls == 1
    quality_report = json.loads(
        (tmp_path / "repo" / result.candidate.quality_report_path).read_text(encoding="utf-8")
    )
    metrics = quality_report["variants"][0]["strategies"][0]["metrics"]
    assert metrics == {
        "manual_case_total": 1,
        "manual_case_confirmed": 1,
        "manual_case_unconfirmed": 0,
        "manual_case_unmapped_ids": [],
    }

    snapshot = harness.get_run(RunRef(workspace_id=result.workspace_id, run_id=result.run_id))
    candidate = snapshot.candidates[0]
    published = harness.review_run(
        ReviewRunCommand(
            workspace_id=result.workspace_id,
            run_id=result.run_id,
            decision=ReviewDecision(
                intent="approve",
                target_artifact="api_test_draft",
                reason="reviewed local vertical-loop fixture",
                reviewed_by="qa_owner",
                versions=[candidate.version_ref(ArtifactVariant.RAW)],
            ),
        )
    )
    assert published.status == "published"

    requests_seen: list[tuple[str, str]] = []

    class Response:
        status_code = 201
        headers = {"X-Business": "must-not-be-persisted"}

        def __init__(self, url: str) -> None:
            self.url = url

        def json(self) -> object:
            return {"message": "must-not-be-persisted"}

    def request(method: str, url: str, **_kwargs: object) -> Response:
        requests_seen.append((method, url))
        return Response(url)

    monkeypatch.setattr("requests.request", request)
    execution = harness.run_api_scenario(
        RunApiScenarioCommand(
            workspace_id=result.workspace_id,
            execution_id="vertical-loop-001",
            environment="qa",
        )
    )

    assert execution.status == "passed"
    assert requests_seen == [("POST", "https://qa.example.test/orders")]
    execution_root = (
        tmp_path / "repo" / "workspaces" / result.workspace_id / "executions" / "vertical-loop-001"
    )
    persisted = "\n".join(
        (execution_root / name).read_text(encoding="utf-8")
        for name in ("manifest.json", "evidence.json", "summary.md")
    )
    assert "must-not-be-persisted" not in persisted

    local_path = repo / "agentic-qa.local.yml"
    local_payload = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    local_payload["secrets"]["values"]["api.orders.qa.auth.fallback_token"] = ""
    local_path.write_text(yaml.safe_dump(local_payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="LOCAL_CONFIG_INVALID"):
        harness.run_api_scenario(
            RunApiScenarioCommand(
                workspace_id=result.workspace_id,
                execution_id="vertical-loop-002",
                environment="qa",
            )
        )
    assert requests_seen == [("POST", "https://qa.example.test/orders")]
    failed_manifest = json.loads(
        (
            tmp_path
            / "repo"
            / "workspaces"
            / result.workspace_id
            / "executions"
            / "vertical-loop-002"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert failed_manifest["status"] == "preflight_failed"
