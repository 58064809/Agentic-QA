from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_runtime_mvp_generation import create_mvp_repo  # noqa: E402

from runtime.graph.app import run_mvp_testcase_generation_workflow  # noqa: E402
from runtime.records.run_id import generate_run_id  # noqa: E402


@pytest.fixture(autouse=True)
def disable_real_llm_by_default(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_runtime_repo(root: Path) -> Path:
    required_files = [
        "AGENTS.md",
        "COMMANDS.md",
        "docs/roadmap.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/02-testcase-generation-workflow.md",
        "prompts/testcase-design-prompt.md",
        "rules/testcase-rules.md",
        "rules/review-gate-rules.md",
        "rules/artifact-path-rules.md",
        "skills/test-design/test-design-skill.md",
        "knowledge/templates/testcase-template.md",
        "prd/demo-requirement/metadata.yml",
        "prd/demo-requirement/input/requirement.md",
    ]
    for relative_path in required_files:
        write_file(root / relative_path)
    (root / "prd/demo-requirement/runs").mkdir(parents=True, exist_ok=True)
    return root


def read_summary_json(result, repo_root: Path) -> dict:
    assert result.run_summary_json is not None
    return json.loads((repo_root / result.run_summary_json).read_text(encoding="utf-8"))


def test_generate_run_id_format_is_stable():
    run_id = generate_run_id(
        now=datetime(2026, 5, 9, 15, 30, 12, tzinfo=UTC),
        random_suffix="a1b2c3",
    )

    assert run_id == "run-20260509-153012-a1b2c3"


def test_dry_run_generates_run_record_by_default(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    assert result.success
    assert result.run_id
    assert result.run_record_dir
    assert result.run_summary_json
    assert result.run_summary_md
    assert (repo_root / result.run_summary_json).is_file()
    assert (repo_root / result.run_summary_md).is_file()
    assert (repo_root / result.run_record_dir / "checkpointer.pkl").is_file()
    assert (repo_root / result.run_record_dir / "graph-state.json").is_file()
    assert (repo_root / result.run_record_dir / "run-state.json").is_file()
    preview_path = repo_root / f"prd/demo-requirement/runs/{result.run_id}/artifact-preview.md"
    assert not preview_path.exists()


def test_record_run_false_does_not_generate_run_record(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.run_id is None
    assert result.run_summary_json is None
    assert not (repo_root / ".runtime/runs").exists()


def test_run_record_json_contains_runtime_summary(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )
    summary = read_summary_json(result, repo_root)

    assert summary["run_id"] == result.run_id
    assert summary["thread_id"] == result.thread_id
    assert summary["success"] is True
    assert summary["run_status"] == "interrupted"
    assert summary["next_action"] == "wait_for_review"
    assert summary["orchestration"] == "YAML WorkflowSpec: testcase_generation"
    assert summary["executed_nodes"]
    assert summary["loaded_files"]
    assert summary["wrote_file"] is False
    assert summary["human_review"]["status"] == "needs_human_review"


def test_run_record_markdown_contains_nodes_and_review_status(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    assert result.run_summary_md is not None
    content = (repo_root / result.run_summary_md).read_text(encoding="utf-8")
    assert "## 节点轨迹" in content
    assert "mvp_command_router_node" in content
    assert "testcase_generator" in content
    assert "review_status：needs_human_review" in content


def test_failed_runtime_flow_still_generates_run_record(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    (repo_root / "prd/demo-requirement/input/requirement.md").unlink()

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )
    summary = read_summary_json(result, repo_root)

    assert not result.success
    assert summary["success"] is False
    assert summary["errors"]
    assert "requirement_normalizer_node" in summary["executed_nodes"]
    assert "mvp_context_loader_node" not in summary["executed_nodes"]
    assert "testcase_generator" not in summary["executed_nodes"]


def test_run_record_does_not_store_full_draft_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )
    summary = read_summary_json(result, repo_root)

    assert "draft_artifact" not in summary
    assert len(summary["draft_artifact_preview"]) <= 300
