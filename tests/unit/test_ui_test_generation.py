from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime_mvp_fixtures import create_mvp_repo  # noqa: E402

from runtime.graph.app import (  # noqa: E402
    resume_recorded_workflow,
    run_ui_test_draft_workflow,
)
from runtime.graph.nodes.ui_test_generation import ui_test_quality_check_node  # noqa: E402
from runtime.graph.state import QAWorkflowState  # noqa: E402
from runtime.llm.config import OpenAICompatibleConfig  # noqa: E402
from runtime.llm.intent_router import route_intent  # noqa: E402
from runtime.workspace import ARTIFACT_SPECS  # noqa: E402


def add_ui_context_files(repo_root: Path) -> None:
    files = {
        "docs/ui-test-generation.md": (REPO_ROOT / "docs/ui-test-generation.md").read_text(
            encoding="utf-8"
        ),
        "prompts/ui-test-generation.md": (REPO_ROOT / "prompts/ui-test-generation.md").read_text(
            encoding="utf-8"
        ),
        "skills/ui-testing.md": (REPO_ROOT / "skills/ui-testing.md").read_text(encoding="utf-8"),
        "workflows/runtime/ui-test-draft.workflow.yml": (
            REPO_ROOT / "workflows/runtime/ui-test-draft.workflow.yml"
        ).read_text(encoding="utf-8"),
    }
    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_ui_test_draft_artifact_spec_is_registered():
    spec = ARTIFACT_SPECS["ui_test_draft"]

    assert spec["current_path"] == "artifacts/ui-test-draft.md"
    assert spec["review_path"] == "reviews/ui-test-draft.review.yml"


def test_intent_routes_ui_test_draft_without_llm(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    route = route_intent(
        "基于 prd/demo-requirement 生成 UI 自动化草稿",
        OpenAICompatibleConfig.from_env(),
    )

    assert route.is_valid
    assert route.intent == "ui_test_draft"
    assert route.prd_path == "prd/demo-requirement"


def test_ui_test_draft_approve_write_only_writes_run_preview(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_ui_context_files(repo_root)

    result = run_ui_test_draft_workflow(
        "生成 UI 自动化草稿",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        use_llm=False,
    )

    assert result.success
    assert result.wrote_file
    preview = repo_root / result.output_paths["ui_test_draft"]
    assert preview.is_file()
    assert preview.as_posix().endswith(
        f"/prd/demo-requirement/runs/{result.run_id}/artifact-preview.md"
    )
    assert not (repo_root / "prd/demo-requirement/artifacts/ui-test-draft.md").exists()


def test_ui_test_draft_fallback_passes_quality_gate_without_llm(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_ui_context_files(repo_root)

    result = run_ui_test_draft_workflow(
        "生成 UI 自动化草稿",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        use_llm=False,
    )

    assert result.success
    assert result.quality_errors == []


def test_android_ui_test_draft_prioritizes_emulator_and_appium(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_ui_context_files(repo_root)

    result = run_ui_test_draft_workflow(
        "基于 Android 模拟器和 APK 生成 UI 自动化草稿，appPackage appActivity UiAutomator2",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        use_llm=False,
    )

    assert result.success
    content = (repo_root / result.output_paths["ui_test_draft"]).read_text(encoding="utf-8")
    for expected in (
        "Android Studio",
        "Android SDK",
        "Emulator",
        "ADB",
        "Appium 2",
        "appium-uiautomator2-driver",
        "ANDROID_DEVICE_NAME",
        "ANDROID_APP_PACKAGE",
        "ANDROID_APP_ACTIVITY",
        "APPIUM_SERVER_URL",
        "resource-id > accessibility id/content-desc > UiSelector text/description",
        "className + 层级辅助 > XPath 兜底",
        "禁止坐标点击作为常规方案",
    ):
        assert expected in content
    assert "生产环境" not in content


def test_ui_test_draft_promote_writes_formal_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_ui_context_files(repo_root)

    result = run_ui_test_draft_workflow(
        "生成 Playwright 测试草稿",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=False,
    )
    resumed = resume_recorded_workflow(
        result.run_id or "",
        action="approve",
        user_input="UI 自动化草稿通过",
        target_artifact="ui_test_draft",
        repo_root=repo_root,
    )
    assert resumed.success
    assert resumed.review_status == "confirmed"
    assert "artifact_promoter" in resumed.executed_nodes
    formal = repo_root / "prd/demo-requirement/artifacts/ui-test-draft.md"
    assert formal.is_file()
    assert "status: confirmed" in formal.read_text(encoding="utf-8")
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/ui-test-draft.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "confirmed"


def test_ui_test_quality_rejects_missing_sections_and_execution_claims(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    state = QAWorkflowState(
        user_input="生成 UI 自动化草稿",
        prd_path="prd/demo-requirement",
        task_type="ui_test_draft",
        run_id="run-1",
        draft_artifacts={"ui_test_draft": "# UI 自动化测试草稿\n\n已执行，执行通过。\n"},
        output_paths={"ui_test_draft": "prd/demo-requirement/runs/run-1/artifact-preview.md"},
    )

    checked = ui_test_quality_check_node(state, repo_root)

    assert any("缺少章节: 自动化脚本草稿" in error for error in checked.quality_errors)
    assert any("执行通过" in error or "已执行" in error for error in checked.quality_errors)
