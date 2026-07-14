from __future__ import annotations

from typing import Any

import yaml


def validate_candidate_front_matter(
    markdown: str,
    *,
    expected_artifact_type: str,
    label: str,
) -> list[str]:
    """Validate the review-state contract shared by candidate Markdown artifacts."""
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return [f"{label}必须以 YAML Front Matter 开头。"]

    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration:
        return [f"{label}的 YAML Front Matter 未闭合。"]

    try:
        metadata: Any = yaml.safe_load("\n".join(lines[1:closing_index])) or {}
    except yaml.YAMLError:
        return [f"{label}的 YAML Front Matter 不是合法 YAML。"]
    if not isinstance(metadata, dict):
        return [f"{label}的 YAML Front Matter 必须是 mapping。"]

    errors: list[str] = []
    if metadata.get("artifact_type") != expected_artifact_type:
        errors.append(f"{label}的 artifact_type 必须是 {expected_artifact_type}。")
    if metadata.get("status") != "needs_human_review":
        errors.append(f"{label}的 status 必须是 needs_human_review。")
    if metadata.get("human_review_required") is not True:
        errors.append(f"{label}的 human_review_required 必须是 true。")
    return errors
