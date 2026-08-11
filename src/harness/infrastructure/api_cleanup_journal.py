from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from harness.domain.schemas.api_execution_reporting import (
    CleanupJournalCounts,
    CleanupJournalSummary,
)
from harness.domain.schemas.api_test_cases import ApiCleanupStep
from harness.infrastructure.persistence.common import atomic_json

UTC = timezone.utc
JOURNAL_SCHEMA = "agentic-qa.api-cleanup-journal.v1"
ENVELOPE_SCHEMA = "agentic-qa.api-cleanup-journal-envelope.v1"


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


class EncryptedCleanupJournal:
    def __init__(
        self,
        path: Path,
        *,
        key: str,
        workspace_id: str,
        execution_id: str,
        environment: str,
        source_cases_sha256: str,
        structural_sha256: str,
        execution_plan_sha256: str,
    ) -> None:
        if not key:
            raise ValueError(
                "runtime.cleanup_journal_key is missing; run `config runtime-key init`"
            )
        self.path = path
        self._key = base64.urlsafe_b64decode(key.encode("ascii"))
        self._aad = execution_id.encode("utf-8")
        self._payload: dict[str, Any] = {
            "schema_version": JOURNAL_SCHEMA,
            "workspace_id": workspace_id,
            "execution_id": execution_id,
            "environment": environment,
            "source_cases_sha256": source_cases_sha256,
            "structural_sha256": structural_sha256,
            "execution_plan_sha256": execution_plan_sha256,
            "created_at": _now(),
            "obligations": [],
        }
        self._save()

    @classmethod
    def load(cls, path: Path, *, key: str) -> EncryptedCleanupJournal:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("schema_version") != ENVELOPE_SCHEMA:
            raise ValueError("cleanup journal envelope schema is unsupported")
        execution_id = str(envelope.get("execution_id") or "")
        decoded_key = base64.urlsafe_b64decode(key.encode("ascii"))
        nonce = base64.urlsafe_b64decode(envelope["nonce"])
        ciphertext = base64.urlsafe_b64decode(envelope["ciphertext"])
        try:
            plaintext = AESGCM(decoded_key).decrypt(
                nonce,
                ciphertext,
                execution_id.encode("utf-8"),
            )
        except Exception as exc:
            raise ValueError("cleanup journal cannot be decrypted with the configured key") from exc
        payload = json.loads(plaintext.decode("utf-8"))
        if payload.get("schema_version") != JOURNAL_SCHEMA:
            raise ValueError("cleanup journal schema is unsupported")
        instance = cls.__new__(cls)
        instance.path = path
        instance._key = decoded_key
        instance._aad = execution_id.encode("utf-8")
        instance._payload = payload
        return instance

    @property
    def payload(self) -> dict[str, Any]:
        return self._payload

    def register(
        self,
        *,
        case_id: str,
        title: str,
        cleanup: ApiCleanupStep,
        runtime_variables: dict[str, Any],
    ) -> str:
        obligation_id = self.arm(
            case_id=case_id,
            title=title,
            cleanup=cleanup,
            runtime_variables=runtime_variables,
            request_operation="legacy-registration",
        )
        self.enrich(
            obligation_id,
            runtime_variables=runtime_variables,
            ready=True,
        )
        return obligation_id

    def arm(
        self,
        *,
        case_id: str,
        title: str,
        cleanup: ApiCleanupStep,
        runtime_variables: dict[str, Any],
        request_operation: str,
        request_idempotency_key: str | None = None,
    ) -> str:
        obligation_id = f"{case_id}::cleanup::{cleanup.id}"
        if any(item["obligation_id"] == obligation_id for item in self._payload["obligations"]):
            raise ValueError(f"cleanup obligation is already registered: {obligation_id}")
        self._payload["obligations"].append(
            {
                "obligation_id": obligation_id,
                "case_id": case_id,
                "title": title,
                "cleanup_id": cleanup.id,
                "state": "armed",
                "armed_at": _now(),
                "mutation_may_happen": True,
                "request_operation": request_operation,
                "request_idempotency_key": request_idempotency_key,
                "step": cleanup.model_dump(mode="json"),
                "runtime_variables": runtime_variables,
            }
        )
        self._save()
        return obligation_id

    def enrich(
        self,
        obligation_id: str,
        *,
        runtime_variables: dict[str, Any],
        ready: bool,
    ) -> None:
        item = self._require(obligation_id)
        if item["state"] != "armed":
            raise ValueError(f"cleanup obligation is not armed: {obligation_id}")
        item["runtime_variables"] = runtime_variables
        item["response_observed_at"] = _now()
        if ready:
            item["state"] = "pending"
            item["registered_at"] = _now()
        self._save()

    def before(self, obligation_id: str) -> None:
        item = self._require(obligation_id)
        if item["state"] != "pending":
            raise ValueError(f"cleanup obligation is not pending: {obligation_id}")
        item["state"] = "running"
        item["started_at"] = _now()
        self._save()

    def after(self, obligation_id: str, *, status: str, request_sent: bool) -> None:
        item = self._require(obligation_id)
        if item["state"] != "running":
            raise ValueError(f"cleanup obligation is not running: {obligation_id}")
        item["state"] = "completed" if status == "passed" else "failed"
        item["request_sent"] = request_sent
        item["completed_at"] = _now()
        item["result_status"] = status
        self._save()

    def pending(self) -> list[dict[str, Any]]:
        return [item for item in self._payload["obligations"] if item["state"] == "pending"]

    def summary(self) -> CleanupJournalSummary:
        obligations = self._payload["obligations"]
        counts = {
            state: sum(item["state"] == state for item in obligations)
            for state in ("armed", "pending", "running", "completed", "failed")
        }
        if not obligations:
            status = "not_required"
        elif counts["armed"] or counts["running"]:
            status = "indeterminate"
        elif counts["failed"]:
            status = "failed"
        elif counts["pending"]:
            status = "pending"
        else:
            status = "complete"
        return CleanupJournalSummary(
            execution_id=self._payload["execution_id"],
            status=status,
            counts=CleanupJournalCounts(total=len(obligations), **counts),
            obligation_ids=[item["obligation_id"] for item in obligations],
        )

    def _require(self, obligation_id: str) -> dict[str, Any]:
        for item in self._payload["obligations"]:
            if item["obligation_id"] == obligation_id:
                return item
        raise KeyError(f"cleanup obligation does not exist: {obligation_id}")

    def _save(self) -> None:
        nonce = os.urandom(12)
        plaintext = json.dumps(
            self._payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        ciphertext = AESGCM(self._key).encrypt(nonce, plaintext, self._aad)
        atomic_json(
            self.path,
            {
                "schema_version": ENVELOPE_SCHEMA,
                "execution_id": self._payload["execution_id"],
                "algorithm": "AES-256-GCM",
                "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
                "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            },
        )
