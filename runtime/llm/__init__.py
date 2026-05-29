"""Lightweight LLM integration helpers for Runtime MVP."""

from runtime.llm.prompt_builder import (
    PromptBuildResult,
    build_api_test_prompt,
    build_archive_prompt,
    build_bug_draft_prompt,
    build_failure_analysis_prompt,
    build_report_prompt,
    build_requirement_analysis_prompt,
    build_test_execution_prompt,
    build_testcase_prompt,
    build_ui_test_prompt,
)

__all__ = [
    "PromptBuildResult",
    "build_requirement_analysis_prompt",
    "build_testcase_prompt",
    "build_api_test_prompt",
    "build_ui_test_prompt",
    "build_test_execution_prompt",
    "build_failure_analysis_prompt",
    "build_bug_draft_prompt",
    "build_report_prompt",
    "build_archive_prompt",
]
