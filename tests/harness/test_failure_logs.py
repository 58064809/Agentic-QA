from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness.domain.schemas.api_execution_reporting import (
    ApiExecutionPlan,
    ApiExecutionPlanCase,
)
from harness.domain.schemas.execution_evidence import (
    CaseExecutionEvidence,
    CorrelationContext,
    ExecutionEnvironment,
    ExecutionEvidence,
    ExecutionSummary,
)
from harness.domain.schemas.local_config import AgenticQaLocalConfig, LocalLogsConfig
from harness.domain.schemas.log_evidence import CollectFailureLogsCommand, LogQueryRequest
from harness.infrastructure.api_execution_snapshot import ExecutionSourceSnapshot
from harness.infrastructure.failure_logs import (
    FilesystemFailureLogService,
    LocalFileLogProvider,
    LokiLogProvider,
)
from harness.infrastructure.log_sanitization import sanitize_log_text
from harness.infrastructure.persistence.common import atomic_json
from harness.infrastructure.persistence.filesystem import FilesystemStore

UTC = timezone.utc


def _logs_config() -> LocalLogsConfig:
    return LocalLogsConfig.model_validate(
        {
            "provider": "local-file",
            "allowed_environments": ["qa"],
            "query": {
                "default_window_seconds": 30,
                "max_window_seconds": 300,
                "default_max_entries": 1000,
                "hard_max_entries": 5000,
                "max_response_bytes": 1024 * 1024,
            },
            "api_service_scopes": {"order-api": ["order-service"]},
            "local_file": {
                "services": {"order-service": {"files": ["local-logs/order-service/*.log"]}},
                "max_files": 10,
                "max_file_bytes": 1024 * 1024,
            },
        }
    )


def _local_config(logs: LocalLogsConfig) -> AgenticQaLocalConfig:
    return AgenticQaLocalConfig.model_validate(
        {
            "schema_version": "agentic-qa.local-config.v1",
            "secrets": {"provider": "local"},
            "model": {
                "provider": "recorded",
                "api_key_env": "MODEL_KEY",
                "flash_model": "recorded-flash",
                "pro_model": "recorded-pro",
            },
            "rag": {"provider": "local-lexical"},
            "postgres": {
                "host": "localhost",
                "database": "postgres",
                "user": "postgres",
                "password": "",
            },
            "test_management": {"provider": "none"},
            "logs": logs.model_dump(mode="json"),
        }
    )


def _query(now: datetime, *, trace_id: str | None = "trace-42") -> LogQueryRequest:
    return LogQueryRequest(
        workspace_id="workspace-1",
        execution_id="execution-1",
        case_id="CASE-1::dataset-a",
        dataset_id="dataset-a",
        environment="qa",
        api_service="order-api",
        services=["order-service"],
        started_at=now,
        completed_at=now,
        max_entries=100,
        trace_id=trace_id,
    )


def test_local_file_provider_filters_by_correlation_and_redacts_before_return(
    tmp_path: Path,
) -> None:
    now = datetime.now(tz=UTC).replace(microsecond=0)
    folder = tmp_path / "local-logs" / "order-service"
    folder.mkdir(parents=True)
    (folder / "app.log").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": now.isoformat(),
                        "level": "ERROR",
                        "message": (
                            "trace-42 request failed Authorization: Bearer secret-token "
                            "phone=13550087714 email=user@example.com"
                        ),
                        "trace_id": "trace-42",
                        "exception_type": "java.sql.SQLException",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": now.isoformat(),
                        "level": "INFO",
                        "message": "unrelated request",
                        "trace_id": "other-trace",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    result, redactions = LocalFileLogProvider(tmp_path, _logs_config()).query(_query(now))

    assert result.status == "success"
    assert len(result.entries) == 1
    assert result.entries[0].trace_id == "trace-42"
    serialized = result.model_dump_json()
    assert "secret-token" not in serialized
    assert "13550087714" not in serialized
    assert "user@example.com" not in serialized
    assert "trace-42" in serialized
    assert redactions >= 3


def test_log_without_timestamp_requires_exact_correlation(tmp_path: Path) -> None:
    folder = tmp_path / "local-logs" / "order-service"
    folder.mkdir(parents=True)
    (folder / "app.log").write_text("ERROR no clock trace-42 timeout\n", encoding="utf-8")
    now = datetime.now(tz=UTC)

    correlated, _ = LocalFileLogProvider(tmp_path, _logs_config()).query(_query(now))
    uncorrelated, _ = LocalFileLogProvider(tmp_path, _logs_config()).query(
        _query(now, trace_id=None)
    )

    assert correlated.status == "success"
    assert uncorrelated.status == "empty"


def test_local_file_provider_rejects_symlinked_log_file(tmp_path: Path) -> None:
    folder = tmp_path / "local-logs" / "order-service"
    folder.mkdir(parents=True)
    target = folder / "target.txt"
    target.write_text("trace-42 error", encoding="utf-8")
    link = folder / "linked.log"
    try:
        os.symlink(target, link)
    except OSError:
        import pytest

        pytest.skip("creating symlinks requires additional Windows permission")

    import pytest

    with pytest.raises(ValueError, match="safe regular file"):
        LocalFileLogProvider(tmp_path, _logs_config()).query(_query(datetime.now(tz=UTC)))


def test_sanitizer_covers_identity_and_credential_patterns() -> None:
    text, count = sanitize_log_text(
        "Bearer abc.def.ghi password=hunter2 access_token=secretvalue "
        "13550087714 user@example.com 11010519491231002X 6222021234567890123"
    )

    assert count >= 7
    assert "hunter2" not in text
    assert "13550087714" not in text
    assert "user@example.com" not in text
    assert "6222021234567890123" not in text


def test_failure_collection_is_create_only_and_reuses_input_hash(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC).replace(microsecond=0)
    store = FilesystemStore(tmp_path)
    workspace_root = store.init_workspace("workspace-1", quality_policies=[])
    execution_root = workspace_root / "executions" / "execution-1"
    execution_root.mkdir(parents=True)
    evidence = ExecutionEvidence(
        schema_version="agentic-qa.execution-evidence.v2",
        run_id="execution-1",
        source_cases_path="published/api_test_draft/history/cases.yml",
        source_cases_schema_version="agentic-qa.api-cases.v1.2",
        started_at=now,
        completed_at=now,
        environment=ExecutionEnvironment(
            name="qa",
            base_url_env="ORDER_API_QA_BASE_URL",
            base_url_configured=True,
            allowed_methods=["GET"],
            request_timeout_seconds=10,
        ),
        summary=ExecutionSummary(total=1, executed=1, passed=0, failed=1, errors=0, blocked=0),
        cases=[
            CaseExecutionEvidence(
                case_id="CASE-1::dataset-a",
                dataset_id="dataset-a",
                title="failed order query",
                method="GET",
                path="/orders/${{id}}",
                status="failed",
                started_at=now,
                completed_at=now,
                duration_ms=5,
                status_code=500,
                request_dispatched=True,
                correlation=CorrelationContext(trace_id="trace-42"),
            )
        ],
    )
    evidence_path = execution_root / "evidence.json"
    atomic_json(evidence_path, evidence.model_dump(mode="json"))
    atomic_json(
        execution_root / "manifest.json",
        {"evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest()},
    )
    plan_payload = {
        "schema_version": "agentic-qa.api-execution-plan.v2",
        "workspace_id": "workspace-1",
        "execution_id": "execution-1",
        "service": "order-api",
        "environment": "qa",
        "created_at": now,
        "source_cases_path": "published/api_test_draft/history/cases.yml",
        "source_cases_sha256": "a" * 64,
        "source_publication_id": "run-1",
        "source_history_path": "published/api_test_draft/history/cases.yml",
        "structural_sha256": "sha256:" + "b" * 64,
        "policy_sha256": "sha256:" + "b" * 64,
        "execution_profile_sha256": "c" * 64,
        "authentication_mode": "none",
        "isolation_mode": "shared",
        "cases": [
            ApiExecutionPlanCase(
                case_id="CASE-1::dataset-a",
                source_case_id="CASE-1",
                dataset_id="dataset-a",
                method="GET",
                path_template="/orders/${{id}}",
                contract_status="confirmed",
                request_structure_sha256="d" * 64,
                operation_classification="read_only",
            )
        ],
    }
    draft_plan = ApiExecutionPlan.model_construct(**plan_payload, plan_sha256="0" * 64)
    hash_payload = draft_plan.model_dump(mode="json", exclude={"plan_sha256"})
    canonical = json.dumps(
        hash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    plan = ApiExecutionPlan.model_validate(
        {**plan_payload, "plan_sha256": hashlib.sha256(canonical).hexdigest()}
    )
    atomic_json(execution_root / "execution-plan.json", plan.model_dump(mode="json"))
    folder = tmp_path / "local-logs" / "order-service"
    folder.mkdir(parents=True)
    (folder / "app.log").write_text(
        json.dumps(
            {
                "timestamp": now.isoformat(),
                "level": "ERROR",
                "message": "trace-42 database timeout",
                "trace_id": "trace-42",
            }
        ),
        encoding="utf-8",
    )
    service = FilesystemFailureLogService(store, _local_config(_logs_config()))
    service._snapshots = _SnapshotStub(  # type: ignore[assignment]
        ExecutionSourceSnapshot(
            workspace_id="workspace-1",
            execution_id="execution-1",
            service="order-api",
            environment="qa",
            source_publication_id="run-1",
            source_history_path="published/api_test_draft/history/cases.yml",
            source_cases_sha256="a" * 64,
            policy_sha256="sha256:" + "b" * 64,
        )
    )
    command = CollectFailureLogsCommand(workspace_id="workspace-1", execution_id="execution-1")

    first = service.collect(command)
    second = service.collect(command)

    assert first == second
    assert first.succeeded == 1
    collection = first.collections[0]
    bundle_path = workspace_root / collection.log_evidence_path
    persisted = bundle_path.read_text(encoding="utf-8")
    assert "database timeout" in persisted
    assert list((bundle_path.parent).glob("log-evidence.json")) == [bundle_path]


class _SnapshotStub:
    def __init__(self, snapshot: ExecutionSourceSnapshot) -> None:
        self._snapshot = snapshot

    def resolve(self, _workspace: str, _execution_id: str) -> ExecutionSourceSnapshot:
        return self._snapshot


class _LokiResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        url: str = "https://logs.qa.example.com/loki/api/v1/query_range",
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.headers: dict[str, str] = {}
        self._body = json.dumps(payload).encode()

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self._body


def _loki_config() -> LocalLogsConfig:
    return LocalLogsConfig.model_validate(
        {
            "provider": "loki",
            "allowed_environments": ["qa"],
            "api_service_scopes": {"order-api": ["gateway", "order-service"]},
            "loki": {
                "base_url": "https://logs.qa.example.com",
                "trusted_origins": ["https://logs.qa.example.com"],
                "token": "provider-resolved-token",
                "service_label": "app",
                "environment_label": "environment",
                "timeout_seconds": 15,
            },
        }
    )


def test_loki_provider_builds_bounded_query_and_redacts_response() -> None:
    now = datetime.now(tz=UTC).replace(microsecond=0)
    captured: dict[str, object] = {}
    response = _LokiResponse(
        {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [
                    {
                        "stream": {"app": "order-service", "environment": "qa"},
                        "values": [
                            [
                                str(int(now.timestamp() * 1_000_000_000)),
                                "ERROR trace-42 timeout Authorization: Bearer leaked-token",
                            ]
                        ],
                    }
                ],
            },
        }
    )

    def request(url: str, **kwargs: object) -> _LokiResponse:
        captured.update({"url": url, **kwargs})
        return response

    result, redactions = LokiLogProvider(_loki_config(), request_func=request).query(_query(now))

    assert result.status == "success"
    assert result.entries[0].service == "order-service"
    assert "leaked-token" not in result.model_dump_json()
    assert redactions >= 1
    assert captured["allow_redirects"] is False
    assert captured["timeout"] == 15
    assert captured["stream"] is True
    assert captured["headers"] == {"Authorization": "Bearer provider-resolved-token"}
    params = captured["params"]
    assert isinstance(params, dict)
    query = str(params["query"])
    assert 'environment="qa"' in query
    assert 'app=~"order\\\\-service"' in query
    assert "trace\\\\-42" in query
    assert "provider-resolved-token" not in query


def test_loki_provider_rejects_redirect_and_out_of_scope_stream() -> None:
    now = datetime.now(tz=UTC).replace(microsecond=0)
    redirect = LokiLogProvider(
        _loki_config(),
        request_func=lambda *_args, **_kwargs: _LokiResponse({}, status_code=302),
    ).query(_query(now))[0]
    outside = LokiLogProvider(
        _loki_config(),
        request_func=lambda *_args, **_kwargs: _LokiResponse(
            {
                "status": "success",
                "data": {
                    "result": [
                        {
                            "stream": {"app": "billing-service", "environment": "qa"},
                            "values": [
                                [str(int(now.timestamp() * 1_000_000_000)), "trace-42 error"]
                            ],
                        }
                    ]
                },
            }
        ),
    ).query(_query(now))[0]

    assert redirect.status == "failed"
    assert redirect.diagnostics[0].code == "LOKI_REDIRECT_REJECTED"
    assert outside.status == "empty"
    assert outside.diagnostics[0].code == "LOKI_STREAM_OUT_OF_SCOPE"


def test_loki_provider_enforces_response_byte_limit() -> None:
    now = datetime.now(tz=UTC)
    response = _LokiResponse({"status": "success", "data": {"result": []}})
    response.headers["Content-Length"] = "99999999"
    result, _ = LokiLogProvider(
        _loki_config(), request_func=lambda *_args, **_kwargs: response
    ).query(_query(now))

    assert result.status == "failed"
    assert result.diagnostics[0].code == "LOKI_QUERY_FAILED"


def test_loki_provider_rejects_excessive_time_window_before_network() -> None:
    now = datetime.now(tz=UTC)
    called = False

    def request(*_args: object, **_kwargs: object) -> _LokiResponse:
        nonlocal called
        called = True
        return _LokiResponse({})

    query = _query(now).model_copy(update={"completed_at": now + timedelta(seconds=301)})
    with pytest.raises(ValueError, match="time window"):
        LokiLogProvider(_loki_config(), request_func=request).query(query)

    assert called is False
