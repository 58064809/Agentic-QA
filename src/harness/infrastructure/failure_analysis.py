from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from harness.domain.schemas.log_analysis import (
    AnalyzeFailureCommand,
    AnalyzeFailureResult,
    FailureAnalysisItem,
    FailureTimelineEvent,
    LogAnalysis,
    LogSignal,
)
from harness.domain.schemas.log_evidence import LogEvidenceBundle
from harness.domain.schemas.trace_evidence import TraceEvidenceBundle
from harness.infrastructure.failure_trace_analysis import derive_trace_analysis
from harness.infrastructure.persistence.common import create_only_json
from harness.infrastructure.persistence.filesystem import FilesystemStore

SIGNALS = (
    ("database", re.compile(r"(?i)sql|database|deadlock|jdbc|psycopg|mysql|postgres")),
    ("redis", re.compile(r"(?i)redis|jedis|lettuce")),
    ("mq", re.compile(r"(?i)kafka|rabbitmq|rocketmq|message queue|consumer|producer")),
    ("rpc", re.compile(r"(?i)grpc|rpc|feign|dubbo")),
    ("timeout", re.compile(r"(?i)timeout|timed out|deadline exceeded")),
    ("network", re.compile(r"(?i)connection reset|connection refused|dns|socket|unreachable")),
    ("http", re.compile(r"(?i)http\s*[45]\d\d|status\s*[45]\d\d|bad gateway|service unavailable")),
)
EXCEPTION = re.compile(
    r"(?m)\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:Exception|Error|Fault))\b"
)
FRAME = re.compile(r"(?m)^\s*(?:at\s+|File\s+\")([^\r\n]+)")
VOLATILE = re.compile(r"\b(?:0x[0-9a-f]+|\d{2,}|[0-9a-f]{16,})\b", re.IGNORECASE)


class FilesystemFailureAnalysisService:
    def __init__(self, store: FilesystemStore) -> None:
        self._store = store

    def analyze(self, command: AnalyzeFailureCommand) -> AnalyzeFailureResult:
        workspace_root = self._store.require_workspace(command.workspace_id).resolve()
        collections_root = (
            workspace_root / "executions" / command.execution_id / "triage" / "collections"
        )
        if not collections_root.is_dir():
            raise ValueError("failure log collections do not exist")
        selected = self._select(collections_root, command)
        if not selected:
            raise ValueError("no matching failure log collection")
        items = [self._analyze_one(path, workspace_root) for path in selected]
        return AnalyzeFailureResult(
            workspace_id=command.workspace_id,
            execution_id=command.execution_id,
            analyses=items,
        )

    def _select(self, root: Path, command: AnalyzeFailureCommand) -> list[Path]:
        paths = [item for item in root.iterdir() if item.is_dir()]
        if command.collection_id:
            return [item for item in paths if item.name == command.collection_id]
        candidates: dict[tuple[str, str | None], list[Path]] = defaultdict(list)
        for path in paths:
            evidence_path = path / "log-evidence.json"
            try:
                if evidence_path.is_file():
                    bundle = LogEvidenceBundle.model_validate_json(
                        evidence_path.read_text(encoding="utf-8")
                    )
                else:
                    bundle = TraceEvidenceBundle.model_validate_json(
                        (path / "trace-evidence.json").read_text(encoding="utf-8")
                    )
            except (OSError, ValueError):
                continue
            if command.case_id and bundle.case_id != command.case_id:
                continue
            key = (bundle.case_id, bundle.dataset_id)
            candidates[key].append(path)
        ambiguous = [key for key, values in candidates.items() if len(values) > 1]
        if ambiguous:
            case_id, dataset_id = sorted(ambiguous)[0]
            raise ValueError(
                "multiple failure log collections match "
                f"{case_id}/{dataset_id or 'default'}; specify collection_id"
            )
        return [values[0] for _, values in sorted(candidates.items())]

    def _analyze_one(self, root: Path, workspace_root: Path) -> FailureAnalysisItem:
        trace_path = root / "trace-evidence.json"
        if trace_path.is_file():
            manifest = json.loads((root / "collection-manifest.json").read_text(encoding="utf-8"))
            trace_raw = trace_path.read_bytes()
            if manifest.get("trace_evidence_sha256") != hashlib.sha256(trace_raw).hexdigest():
                raise ValueError("trace evidence hash does not match collection manifest")
            trace_bundle = TraceEvidenceBundle.model_validate_json(trace_raw)
            target = root / "trace-analysis.json"
            if target.exists():
                from harness.domain.schemas.trace_analysis import TraceAnalysis

                TraceAnalysis.model_validate_json(target.read_text(encoding="utf-8"))
            else:
                trace_analysis = derive_trace_analysis(
                    trace_bundle, hashlib.sha256(trace_raw).hexdigest()
                )
                create_only_json(target, trace_analysis.model_dump(mode="json"))
        evidence_path = root / "log-evidence.json"
        if not evidence_path.is_file():
            return FailureAnalysisItem(
                collection_id=trace_bundle.collection_id,
                case_id=trace_bundle.case_id,
                dataset_id=trace_bundle.dataset_id,
                analysis_status=(
                    "empty"
                    if trace_bundle.status != "success" or not trace_bundle.spans
                    else "success"
                ),
                log_analysis_path=(root / "trace-analysis.json")
                .relative_to(workspace_root)
                .as_posix(),
            )
        manifest = json.loads((root / "collection-manifest.json").read_text(encoding="utf-8"))
        raw = evidence_path.read_bytes()
        if manifest.get("log_evidence_sha256") != hashlib.sha256(raw).hexdigest():
            raise ValueError("log evidence hash does not match collection manifest")
        bundle = LogEvidenceBundle.model_validate_json(raw)
        target = root / "log-analysis.json"
        if target.exists():
            analysis = LogAnalysis.model_validate_json(target.read_text(encoding="utf-8"))
        else:
            analysis = self._derive(bundle, hashlib.sha256(raw).hexdigest())
            create_only_json(target, analysis.model_dump(mode="json"))
        return FailureAnalysisItem(
            collection_id=bundle.collection_id,
            case_id=bundle.case_id,
            dataset_id=bundle.dataset_id,
            analysis_status="success" if analysis.signals else "empty",
            log_analysis_path=target.relative_to(workspace_root).as_posix(),
        )

    @staticmethod
    def _derive(bundle: LogEvidenceBundle, evidence_sha: str) -> LogAnalysis:
        groups: dict[tuple[str, str, str, tuple[str, ...]], list] = defaultdict(list)
        timeline = [
            FailureTimelineEvent(
                reference="EXEC-0001",
                timestamp=bundle.query.started_at,
                source="execution",
                event="failure query window started",
            )
        ]
        for entry in bundle.entries:
            text = entry.message
            exception = entry.exception_type or (
                EXCEPTION.search(text).group(1) if EXCEPTION.search(text) else None
            )
            category = "exception" if exception else ""
            if not category:
                category = next((name for name, pattern in SIGNALS if pattern.search(text)), "")
            timeline.append(
                FailureTimelineEvent(
                    reference=entry.entry_id,
                    timestamp=entry.timestamp,
                    source="log",
                    service=entry.service,
                    event=f"{entry.level} log observed",
                )
            )
            if not category:
                continue
            normalized = VOLATILE.sub("<value>", " ".join(text.split()))[:1000]
            frames = tuple(FRAME.findall(text)[:10])
            groups[(entry.service, category, exception or "", normalized, frames)].append(entry)
        signals: list[LogSignal] = []
        for index, (key, entries) in enumerate(sorted(groups.items()), 1):
            service, category, exception, normalized, frames = key
            fingerprint = hashlib.sha256(
                json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest()
            timestamps = [item.timestamp for item in entries if item.timestamp]
            signals.append(
                LogSignal(
                    signal_id=f"SIGNAL-{index:04d}",
                    category=category,
                    service=service,
                    fingerprint=fingerprint,
                    exception_type=exception or None,
                    normalized_message=normalized,
                    top_frames=list(frames),
                    occurrence_count=len(entries),
                    first_seen=min(timestamps) if timestamps else None,
                    last_seen=max(timestamps) if timestamps else None,
                    sample_refs=[item.entry_id for item in entries[:10]],
                )
            )
        timeline.sort(key=lambda item: (item.timestamp is None, item.timestamp, item.reference))
        payload = {
            "schema_version": "agentic-qa.log-analysis.v1",
            "collection_id": bundle.collection_id,
            "execution_id": bundle.execution_id,
            "case_id": bundle.case_id,
            "dataset_id": bundle.dataset_id,
            "log_evidence_sha256": evidence_sha,
            "signals": [item.model_dump(mode="json") for item in signals[:300]],
            "timeline": [item.model_dump(mode="json") for item in timeline],
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return LogAnalysis.model_validate({**payload, "content_sha256": digest})
