from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from harness.infrastructure.persistence.filesystem import FilesystemStore


class HistoricalSourceUnavailableError(ValueError):
    code = "HISTORICAL_SOURCE_UNAVAILABLE"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")


@dataclass(frozen=True)
class PublishedApiSource:
    path: Path
    workspace_relative_path: str
    publication_id: str
    content_sha256: str
    content: bytes


class PublishedApiSourceResolver:
    def __init__(self, store: FilesystemStore) -> None:
        self._store = store

    def resolve_current(self, workspace: str) -> PublishedApiSource:
        root = self._store.require_workspace(workspace).resolve()
        current = root / "published" / "api_test_draft" / "current.yml"
        if not current.is_file():
            raise HistoricalSourceUnavailableError("current published API cases are missing")
        current_sha256 = _sha256(current.read_bytes())
        matches = [
            item
            for item in self._history_versions(root)
            if item.get("content_sha256") == current_sha256
        ]
        if not matches:
            raise HistoricalSourceUnavailableError(
                "current published API cases are not recorded in publication history"
            )
        latest = matches[-1]
        return self._resolve_entry(root, latest, expected_sha256=current_sha256)

    def resolve_historical(
        self,
        workspace: str,
        *,
        publication_id: str | None,
        history_path: str | None,
        expected_sha256: str,
    ) -> PublishedApiSource:
        root = self._store.require_workspace(workspace).resolve()
        versions = self._history_versions(root)
        if publication_id and history_path:
            matches = [
                item
                for item in versions
                if item.get("run_id") == publication_id and item.get("path") == history_path
            ]
        else:
            # Legacy execution plans did not persist publication identity. A unique
            # historical hash is the only safe deterministic migration path.
            matches = [item for item in versions if item.get("content_sha256") == expected_sha256]
        if len(matches) != 1:
            raise HistoricalSourceUnavailableError(
                "execution source cannot be resolved to exactly one historical publication"
            )
        return self._resolve_entry(root, matches[0], expected_sha256=expected_sha256)

    @staticmethod
    def _history_versions(root: Path) -> list[dict[str, Any]]:
        index_path = root / "published" / "api_test_draft" / "history" / "index.yml"
        if not index_path.is_file():
            raise HistoricalSourceUnavailableError("publication history index is missing")
        try:
            payload = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise HistoricalSourceUnavailableError(
                "publication history index cannot be read"
            ) from exc
        if payload.get("schema_version") != "agentic-qa.harness.history.v2":
            raise HistoricalSourceUnavailableError("publication history schema is unsupported")
        versions = payload.get("versions")
        if not isinstance(versions, list) or not all(isinstance(item, dict) for item in versions):
            raise HistoricalSourceUnavailableError("publication history entries are invalid")
        return versions

    @staticmethod
    def _resolve_entry(
        root: Path,
        entry: dict[str, Any],
        *,
        expected_sha256: str,
    ) -> PublishedApiSource:
        publication_id = entry.get("run_id")
        relative_path = entry.get("path")
        recorded_sha256 = entry.get("content_sha256")
        if not all(isinstance(item, str) and item for item in (publication_id, relative_path)):
            raise HistoricalSourceUnavailableError("publication history identity is invalid")
        if recorded_sha256 != expected_sha256:
            raise HistoricalSourceUnavailableError(
                "publication history hash does not match execution"
            )
        path = (root / relative_path).resolve()
        history_root = (root / "published" / "api_test_draft" / "history").resolve()
        if path.parent != history_root or not path.is_file():
            raise HistoricalSourceUnavailableError("historical API cases path is unavailable")
        content = path.read_bytes()
        if _sha256(content) != expected_sha256:
            raise HistoricalSourceUnavailableError("historical API cases content was modified")
        return PublishedApiSource(
            path=path,
            workspace_relative_path=path.relative_to(root).as_posix(),
            publication_id=publication_id,
            content_sha256=expected_sha256,
            content=content,
        )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
