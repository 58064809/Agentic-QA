from __future__ import annotations

from typing import Any

from actions.requirement_parser import derive_business_rules
from actions.requirement_parser import extract_requirement_items
from actions.requirement_parser import split_questions


def _build_test_name(index: int) -> str:
    return f"test_requirement_{index:03d}"


def generate_test_script(user_text: str, requirement_context: dict[str, Any]) -> dict[str, Any]:
    items = extract_requirement_items(user_text, requirement_context)
    requirement_items, open_questions = split_questions(items)
    business_rules = derive_business_rules(requirement_items)[:5]

    lines = [
        "import pytest",
        "",
        "",
        "class TestGeneratedFromRequirement:",
    ]

    if not business_rules:
        lines.extend(
            [
                "    def test_placeholder(self):",
                '        """Provide a concrete requirement or PRD path before generating script."""',
                '        raise NotImplementedError("Requirement details are missing.")',
            ]
        )
    else:
        for index, rule in enumerate(business_rules, start=1):
            lines.extend(
                [
                    "",
                    f"    @pytest.mark.case_{index}",
                    f"    def {_build_test_name(index)}(self):",
                    f'        """{rule}"""',
                    f"        # TODO: prepare data for: {rule}",
                    f"        # TODO: execute the action described in the requirement",
                    f"        # TODO: assert the expected result for: {rule}",
                    '        raise NotImplementedError("Implement this test based on the requirement.")',
                ]
            )

    return {
        "task": "script_generation",
        "analysis_basis": {
            "requirement_docs": [doc["path"] for doc in requirement_context.get("selected_requirement_docs", [])],
            "prototype_assets": [asset["path"] for asset in requirement_context.get("selected_prototypes", [])],
        },
        "open_questions": open_questions,
        "recommended_file_name": "test_generated_from_requirement.py",
        "script_language": "python",
        "script_framework": "pytest",
        "script_content": "\n".join(lines) + "\n",
    }
