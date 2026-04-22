from __future__ import annotations

from pathlib import Path
from typing import Any


def search_logs(file_path: str, keyword: str) -> dict[str, Any]:
    """最小日志检索骨架。

    当前版本只支持本地文件关键词扫描，后续再补时间范围、traceId、服务名等能力。
    """
    path = Path(file_path)
    if not path.exists():
        return {
            'task': 'log_analysis',
            'error': f'log file not found: {file_path}',
            'matches': [],
        }

    matches: list[str] = []
    for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        if keyword.lower() in line.lower():
            matches.append(line)

    return {
        'task': 'log_analysis',
        'file_path': file_path,
        'keyword': keyword,
        'match_count': len(matches),
        'matches': matches[:50],
    }
