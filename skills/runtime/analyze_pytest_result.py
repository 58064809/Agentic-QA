from __future__ import annotations

from typing import Any


def analyze_pytest_result(raw_text: str) -> dict[str, Any]:
    """最小 pytest 结果分析骨架。

    当前版本先按关键字粗分类型，后续再补更细的失败归因逻辑。
    """
    text = raw_text.lower()
    error_type = 'unknown'
    if 'assert' in text:
        error_type = 'assertion_error'
    elif 'timeout' in text:
        error_type = 'timeout'
    elif 'connection' in text:
        error_type = 'connection_error'

    return {
        'task': 'result_analysis',
        'error_type': error_type,
        'summary': raw_text[:500],
        'possible_causes': [],
        'next_actions': [],
    }
