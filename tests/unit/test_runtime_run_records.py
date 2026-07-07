from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_mvp_fixtures import create_mvp_repo  # noqa: E402

from runtime.graph.app import run_mvp_testcase_generation_workflow  # noqa: E402
from runtime.records.run_id import generate_run_id  # noqa: E402
from runtime.workflow.runner import retry_failed_workflow_for_run  # noqa: E402


@pytest.fixture(autouse=True)
def disable_real_llm_by_default(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


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
    assert (repo_root / result.run_record_dir / "checkpoint-manifest.json").is_file()
    assert not (repo_root / result.run_record_dir / "checkpointer.pkl").exists()
    assert (repo_root / result.run_record_dir / "graph-state.json").is_file()
    assert (repo_root / result.run_record_dir / "run-state.json").is_file()
    preview_path = repo_root / f"prd/demo-requirement/runs/{result.run_id}/artifact-preview.md"
    assert preview_path.exists()


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
    assert summary["wrote_file"] is True
    assert summary["human_review"]["status"] == "needs_human_review"
    assert summary["checkpoint"]["storage"] == "postgres"
    assert summary["checkpoint"]["checkpoint_file"] is None
    assert summary["checkpoint"]["dsn_env"] == "AGENTIC_QA_CHECKPOINT_POSTGRES_DSN"


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
    assert "testcase_generation_node" in content
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
    assert "testcase_generation_node" not in summary["executed_nodes"]


def test_postgres_checkpointer_missing_dsn_generates_failed_run_record(tmp_path, monkeypatch):
    repo_root = create_mvp_repo(tmp_path)
    monkeypatch.delenv("AGENTIC_QA_CHECKPOINT_POSTGRES_DSN", raising=False)
    (repo_root / "configs").mkdir(parents=True, exist_ok=True)
    (repo_root / "configs/local.yaml").write_text(
        """
runtime:
  checkpointer: postgres
  checkpoint_postgres_dsn_env: AGENTIC_QA_CHECKPOINT_POSTGRES_DSN
""",
        encoding="utf-8",
    )

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )
    summary = read_summary_json(result, repo_root)

    assert not result.success
    assert result.run_status == "failed"
    assert result.next_action == "retry"
    assert "未设置 PostgreSQL checkpointer 连接串环境变量" in result.errors[0]
    assert summary["checkpoint"] == {}
    assert not (repo_root / result.run_record_dir / "checkpointer.pkl").exists()


def test_failed_runtime_flow_can_retry_same_thread_after_input_fix(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    requirement_path = repo_root / "prd/demo-requirement/input/requirement.md"
    original = requirement_path.read_text(encoding="utf-8")
    requirement_path.unlink()

    failed = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    assert not failed.success
    assert failed.run_status == "failed"
    assert failed.next_action is None
    requirement_path.write_text(original, encoding="utf-8")

    retried = retry_failed_workflow_for_run(
        failed.run_id or "",
        user_input="修复输入后重试",
        repo_root=repo_root,
    )

    assert retried.success
    assert retried.run_id == failed.run_id
    assert retried.thread_id == failed.thread_id
    assert retried.run_status == "interrupted"
    assert retried.review_status == "needs_human_review"
    assert retried.next_action == "wait_for_review"
    assert "testcase_generation_node" in retried.executed_nodes
    summary = read_summary_json(retried, repo_root)
    assert summary["checkpoint"]["storage"] == "postgres"


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
