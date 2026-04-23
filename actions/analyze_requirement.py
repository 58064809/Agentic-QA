from __future__ import annotations

from typing import Any

from actions.requirement_parser import derive_business_rules
from actions.requirement_parser import derive_risks
from actions.requirement_parser import derive_test_focus
from actions.requirement_parser import extract_requirement_items
from actions.requirement_parser import normalize_text
from actions.requirement_parser import split_questions
from actions.test_model_builder import build_test_model


def analyze_requirement(user_text: str, requirement_context: dict[str, Any]) -> dict[str, Any]:
    items = extract_requirement_items(user_text, requirement_context)
    requirement_items, parser_questions = split_questions(items)
    business_rules = derive_business_rules(requirement_items)
    generic_test_focus = derive_test_focus(requirement_items)
    generic_risks = derive_risks(requirement_items)
    model = build_test_model(
        user_text=user_text,
        requirement_context=requirement_context,
        requirement_items=requirement_items,
        business_rules=business_rules,
        generic_risks=generic_risks,
        existing_questions=parser_questions,
    )
    acceptance_criteria = [
        "核心资金链路的金额、状态、流水、权限四项数据一致",
        "PRD 中的业务规则均能落到页面提示、接口校验、数据库状态和操作日志",
        "异常、重复提交、并发、权限不足场景有明确兜底，不产生脏数据或重复资金动作",
    ]
    next_actions: list[str] = []

    if requirement_context.get("missing_context"):
        next_actions.extend(requirement_context["missing_context"])
    if model["open_questions"]:
        next_actions.append("先确认待确认项，再冻结测试范围和 P0/P1 用例")
    if not requirement_items:
        next_actions.append("当前没有发现足够明确的需求条目，建议指定 PRD 路径或补充需求目录")
    else:
        next_actions.append("下一步可直接生成测试用例表，按 P0/P1/P2 和页面/接口/数据层分组")

    return {
        "_ok": True,
        "_metadata": {
            "requirement_item_count": len(requirement_items),
            "open_question_count": len(model["open_questions"]),
        },
        "task": "requirement_analysis",
        "summary": normalize_text(user_text)[:200],
        "analysis_basis": {
            "requirement_package": requirement_context.get("requirement_package"),
            "requirement_docs": [doc["path"] for doc in requirement_context.get("selected_requirement_docs", [])],
            "prototype_assets": [asset["path"] for asset in requirement_context.get("selected_prototypes", [])],
        },
        "requirement_items": requirement_items,
        "business_rules": business_rules,
        "test_focus": generic_test_focus,
        "risks": generic_risks,
        "acceptance_criteria": acceptance_criteria,
        "next_actions": next_actions,
        **model,
    }
