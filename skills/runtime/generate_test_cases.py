from __future__ import annotations

from typing import Any


def generate_test_cases(text: str) -> dict[str, Any]:
    """最小测试用例生成骨架。

    当前版本先返回统一结构，后续再补规则拆解与表格生成逻辑。
    """
    return {
        'task': 'test_case_generation',
        'input_summary': text[:200],
        'columns': ['标题', '优先级', '前置条件', '测试步骤', '预期结果'],
        'cases': [],
    }
