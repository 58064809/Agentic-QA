from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ALLOWED_ARTIFACT_STATUSES = {
    "draft",
    "partial",
    "needs_human_review",
    "approved",
    "needs_changes",
    "rejected",
    "confirmed",
    "archived",
    "failed",
    "superseded",
}

BLOCKING_ARTIFACT_STATUSES = {"needs_human_review", "needs_changes", "partial", "failed"}

REQUIRED_METADATA_KEYS = [
    "requirement_id",
    "title",
    "status",
    "created_by",
    "created_at",
    "updated_at",
    "artifacts",
    "reviews",
]

ARTIFACT_SPECS: dict[str, dict[str, str]] = {
    "requirement_analysis": {
        "artifact_type": "requirement_analysis",
        "current_path": "artifacts/requirement-analysis.md",
        "history_index": "artifacts/history/requirement-analysis/index.yml",
        "review_path": "reviews/requirement-analysis.review.yml",
    },
    "testcases": {
        "artifact_type": "testcases",
        "current_path": "artifacts/testcases.md",
        "history_index": "artifacts/history/testcases/index.yml",
        "review_path": "reviews/testcases.review.yml",
    },
    "api_test_draft": {
        "artifact_type": "api_test_draft",
        "current_path": "artifacts/api-test-draft.md",
        "history_index": "artifacts/history/api-test-draft/index.yml",
        "review_path": "reviews/api-test-draft.review.yml",
    },
    "ui_test_draft": {
        "artifact_type": "ui_test_draft",
        "current_path": "artifacts/ui-test-draft.md",
        "history_index": "artifacts/history/ui-test-draft/index.yml",
        "review_path": "reviews/ui-test-draft.review.yml",
    },
    "api_discovery_report": {
        "artifact_type": "api_discovery_report",
        "current_path": "artifacts/api-discovery-report.md",
        "history_index": "artifacts/history/api-discovery-report/index.yml",
        "review_path": "reviews/api-discovery-report.review.yml",
    },
    "qa_report": {
        "artifact_type": "qa_report",
        "current_path": "artifacts/qa-report.md",
        "history_index": "artifacts/history/qa-report/index.yml",
        "review_path": "reviews/qa-report.review.yml",
    },
}

WORKSPACE_DIRS = [
    "input",
    "input/attachments",
    "artifacts",
    "artifacts/history",
    "reviews",
    "runs",
    *dict.fromkeys(
        str(Path(spec["history_index"]).parent).replace("\\", "/")
        for spec in ARTIFACT_SPECS.values()
    ),
]

REQUIRED_WORKSPACE_FILES = [
    "input/requirement.md",
    "input/api.md",
    "metadata.yml",
    *[spec["review_path"] for spec in ARTIFACT_SPECS.values()],
    *[spec["history_index"] for spec in ARTIFACT_SPECS.values()],
]

METADATA_FILE = "metadata.yml"
RUNS_DIR = "runs"
ARTIFACT_PREVIEW_FILE = "artifact-preview.md"
DIFF_FILE = "diff.md"
QUALITY_CHECK_FILE = "quality-check.json"


def resolve_prd_path(repo_root: Path, prd_path: str) -> Path:
    """Resolve a PRD path: absolute paths used as-is; relative paths under repo_root."""
    path = Path(prd_path)
    return path if path.is_absolute() else repo_root / path


def now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须是 YAML 对象")
    return data


def write_yaml_mapping(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def history_index(artifact: str, artifact_type: str) -> dict[str, Any]:
    return {
        "artifact": artifact,
        "artifact_type": artifact_type,
        "current_version": "",
        "versions": [],
    }


def review_record(artifact: str, artifact_type: str) -> dict[str, Any]:
    return {
        "artifact": artifact,
        "artifact_type": artifact_type,
        "status": "needs_human_review",
        "reviewer": "",
        "reviewed_at": None,
        "decision": "",
        "comments": [],
        "required_changes": [],
        "approved_sections": [],
        "rejected_sections": [],
        "next_action": "",
        "source_message": "",
        "run_id": "",
    }


def default_metadata(slug: str, title: str, created_by: str) -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "requirement_id": slug,
        "title": title,
        "status": "draft",
        "created_by": created_by,
        "created_at": timestamp,
        "updated_at": timestamp,
        "artifacts": {
            key: {
                "current_path": spec["current_path"],
                "current_version": "",
                "history_index": spec["history_index"],
                "latest_run_id": "",
                "status": "draft",
            }
            for key, spec in ARTIFACT_SPECS.items()
        },
        "reviews": {key: spec["review_path"] for key, spec in ARTIFACT_SPECS.items()},
    }


def combined_artifact_preview(draft_artifacts: dict[str, str]) -> str:
    if not draft_artifacts:
        return ""
    if len(draft_artifacts) == 1:
        return next(iter(draft_artifacts.values()))

    sections: list[str] = [
        "---",
        "artifact_type: artifact_preview",
        "status: needs_human_review",
        "human_review_required: true",
        "generated_by: agentic-qa-runtime",
        "---",
        "",
        "# 候选产物预览",
        "",
    ]
    titles = {
        "requirement_analysis": "需求分析候选",
        "testcases": "测试用例候选",
        "api_test_draft": "接口测试草稿候选",
        "ui_test_draft": "UI 自动化草稿候选",
        "api_discovery_report": "接口发现报告候选",
        "qa_report": "QA 报告候选",
    }
    for key, content in draft_artifacts.items():
        sections.append(f"<!-- artifact:start {key} -->")
        sections.append("")
        sections.append(f"## {titles.get(key, key)}")
        sections.append("")
        sections.append(content.strip())
        sections.append("")
        sections.append(f"<!-- artifact:end {key} -->")
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"


@dataclass(frozen=True)
class PRDWorkspace:
    root: Path

    @property
    def metadata_path(self) -> Path:
        return self.root / METADATA_FILE

    @property
    def requirement_path(self) -> Path:
        return self.root / "input/requirement.md"

    @property
    def api_path(self) -> Path:
        return self.root / "input/api.md"

    @property
    def runs_dir(self) -> Path:
        return self.root / RUNS_DIR

    def run_dir(self, run_id: str | None) -> Path:
        return self.runs_dir / (run_id or "runtime")

    def artifact_preview_path(self, run_id: str | None) -> Path:
        return self.run_dir(run_id) / ARTIFACT_PREVIEW_FILE

    def diff_path(self, run_id: str | None) -> Path:
        return self.run_dir(run_id) / DIFF_FILE

    def quality_check_path(self, run_id: str | None) -> Path:
        return self.run_dir(run_id) / QUALITY_CHECK_FILE

    def current_artifact_path(self, artifact_key: str) -> Path:
        spec = ARTIFACT_SPECS[artifact_key]
        return self.root / spec["current_path"]

    def review_path(self, artifact_key: str) -> Path:
        spec = ARTIFACT_SPECS[artifact_key]
        return self.root / spec["review_path"]

    def load_metadata(self) -> dict[str, Any]:
        if self.metadata_path.is_file():
            return read_yaml_mapping(self.metadata_path)
        return {}

    def ensure_directories(self) -> None:
        for directory in WORKSPACE_DIRS:
            (self.root / directory).mkdir(parents=True, exist_ok=True)
