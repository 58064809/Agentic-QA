from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from create_prd_workspace import (  # noqa: E402
    WORKSPACE_DIRS,
    archive_requirement,
    create_workspace,
    generate_markdown_report,
    validate_workspace,
)


def test_create_prd_workspace_creates_standard_directories(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    assert (workspace / "requirement.md").is_file()
    assert (workspace / "api-doc.md").is_file()
    assert (workspace / "metadata.yml").is_file()
    for directory in WORKSPACE_DIRS:
        assert (workspace / directory).is_dir()


def test_validate_prd_workspace_accepts_standard_workspace(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    result = validate_workspace(workspace)

    assert result.ok, result.errors


def test_generate_markdown_report_creates_report_draft(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    report = generate_markdown_report(workspace)
    content = report.read_text(encoding="utf-8")

    assert report.is_file()
    assert "QA 报告草稿" in content
    assert "产物索引" in content
    assert "待人工确认项" in content


def test_generate_markdown_report_summarizes_without_full_testcase_table(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")
    testcase_table = """---
status: needs_human_review
human_review_required: true
---

# 测试用例草稿

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
| 登录成功返回 token | P0 | 用户存在 | 1. 调用登录接口 | 返回 access_token |
| 手机号格式错误 | P1 | 无 | 1. 输入 12345 | 返回格式错误 |

## 待人工审核

- [ ] 确认锁定策略。
"""
    (workspace / "20-testcases" / "testcases.md").write_text(
        testcase_table, encoding="utf-8"
    )

    report = generate_markdown_report(workspace)
    content = report.read_text(encoding="utf-8")

    assert "产物索引" in content
    assert "待人工确认项" in content
    assert "已识别测试用例 2 条" in content
    assert "| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |" not in content
    assert "| 登录成功返回 token | P0 | 用户存在 |" not in content
    assert "tok\n" not in content


def test_archive_requirement_rejects_unreviewed_workspace(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    with pytest.raises(RuntimeError, match="拒绝归档"):
        archive_requirement(workspace)
