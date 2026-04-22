from __future__ import annotations

from typing import Any


def analyze_requirement(text: str) -> dict[str, Any]:
    """最小需求分析骨架。

    当前版本先返回统一结构，后续再补真正的规则提取逻辑。
    """
    return {
        'task': 'requirement_analysis',
        'summary': text[:200],
        'business_goal': '',
        'rules': [],
        'test_points': [],
        'risks': [],
        'pending_questions': [],
    }
