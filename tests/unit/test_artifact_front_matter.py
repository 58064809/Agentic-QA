from runtime.validators.artifact_front_matter import validate_candidate_front_matter


def test_candidate_front_matter_accepts_exact_review_contract():
    markdown = """---
artifact_type: testcases
status: needs_human_review
human_review_required: true
---

# 测试用例草稿
"""

    assert (
        validate_candidate_front_matter(
            markdown,
            expected_artifact_type="testcases",
            label="测试用例草稿",
        )
        == []
    )


def test_candidate_front_matter_rejects_contract_drift():
    markdown = """---
artifact_type: testcase_draft
status: confirmed
human_review_required: false
---
"""

    errors = validate_candidate_front_matter(
        markdown,
        expected_artifact_type="testcases",
        label="测试用例草稿",
    )

    assert errors == [
        "测试用例草稿的 artifact_type 必须是 testcases。",
        "测试用例草稿的 status 必须是 needs_human_review。",
        "测试用例草稿的 human_review_required 必须是 true。",
    ]


def test_candidate_front_matter_must_be_first_and_valid_yaml():
    assert validate_candidate_front_matter(
        "# 标题\n\nstatus: needs_human_review",
        expected_artifact_type="qa_report",
        label="QA 报告草稿",
    ) == ["QA 报告草稿必须以 YAML Front Matter 开头。"]
    assert validate_candidate_front_matter(
        "---\nartifact_type: [\n---\n",
        expected_artifact_type="qa_report",
        label="QA 报告草稿",
    ) == ["QA 报告草稿的 YAML Front Matter 不是合法 YAML。"]
