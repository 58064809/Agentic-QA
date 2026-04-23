from __future__ import annotations

import re
from typing import Any

from actions.automation_standards import FLAKY_TEST_HEURISTICS


def _extract_failure_locations(raw_text: str) -> list[str]:
    locations: list[str] = []
    for line in raw_text.splitlines():
        if re.match(r"^FAILED\s+.+::", line.strip()):
            locations.append(line.strip())
        elif re.search(r"[A-Za-z0-9_./\\-]+\.py:\d+", line):
            locations.append(line.strip())
    return locations[:8]


def _extract_pytest_summary(raw_text: str) -> str:
    for line in reversed(raw_text.splitlines()):
        if " failed" in line or " passed" in line or " error" in line or " selected" in line:
            if re.search(r"=+.+in\s+\d", line):
                return line.strip("= ").strip()
    return raw_text[:300]


def _has_meaningful_flaky_signal(raw_text: str) -> bool:
    signal_patterns = (
        "rerun ",
        "reruns",
        "flaky",
        "retrying",
        "retried",
        "xpass",
    )
    ignored_patterns = (
        "plugins:",
        "rerunfailures",
    )
    for raw_line in raw_text.lower().splitlines():
        line = raw_line.strip()
        if not line or any(ignored in line for ignored in ignored_patterns):
            continue
        if any(signal in line for signal in signal_patterns):
            return True
    return False


def analyze_pytest_result(raw_text: str, execution_result: dict[str, Any] | None = None) -> dict[str, Any]:
    text = raw_text.lower()
    error_type = "unknown"
    possible_causes: list[str] = []
    next_actions: list[str] = []
    evidence: list[str] = []
    flaky_signals: list[str] = []
    confidence = 0.2

    if execution_result and execution_result.get("exit_code") == 124:
        error_type = "pytest_timeout"
        confidence = 0.95
        evidence.append("pytest execution exceeded timeout")
        possible_causes = [
            "测试执行超过超时时间",
            "用例存在阻塞等待、死循环或依赖服务无响应",
        ]
        next_actions = [
            "先单独执行最后一个疑似阻塞用例",
            "检查等待条件、网络依赖和 fixture teardown",
        ]
    elif "file or directory not found" in text:
        error_type = "path_not_found"
        confidence = 0.9
        evidence.append("pytest reported file or directory not found")
        possible_causes = [
            "pytest 目标路径不存在",
            "当前工作目录不对，导致相对路径解析失败",
        ]
        next_actions = [
            "检查 target 参数是否存在",
            "检查 pytest 的 cwd 是否为仓库根目录",
        ]
    elif "0 selected" in text or "collected 0 items" in text or "deselected / 0 selected" in text:
        error_type = "no_tests_selected"
        confidence = 0.9
        evidence.append("pytest selected no tests")
        possible_causes = [
            "pytest 的 -k 或 -m 条件没有命中任何用例",
            "测试文件名、用例名或 marker 与实际用例不一致",
        ]
        next_actions = [
            "去掉 -k 或 -m 再执行一次",
            "先执行 pytest tests 确认基础收集是否正常",
        ]
    elif "assertionerror" in text or " assert " in text:
        error_type = "assertion_error"
        confidence = 0.85
        evidence.append("AssertionError or assert expression found")
        possible_causes = [
            "断言结果与预期不一致",
            "接口返回、页面状态或落库数据发生偏差",
        ]
        next_actions = [
            "查看失败断言位置和实际值",
            "对比预期值、接口返回值和环境数据",
        ]
    elif "timeout" in text:
        error_type = "timeout"
        confidence = 0.75
        evidence.append("timeout keyword found")
        flaky_signals.extend(
            [
                "可能存在异步等待、服务响应慢、动画/遮罩未消失或依赖环境抖动",
                "如果重跑后通过，应按 flaky 处理而不是直接忽略",
            ]
        )
        possible_causes = [
            "接口响应超时或等待条件超时",
            "环境性能抖动或依赖服务异常",
        ]
        next_actions = [
            "检查超时点和依赖服务状态",
            "结合日志确认是环境问题还是业务问题",
        ]
    elif "connection" in text:
        error_type = "connection_error"
        confidence = 0.75
        evidence.append("connection keyword found")
        flaky_signals.append("连接类失败需要区分环境不可用、服务未启动、DNS/端口错误和测试数据问题")
        possible_causes = [
            "网络连接失败或目标服务不可达",
            "测试环境未启动或地址配置错误",
        ]
        next_actions = [
            "检查环境连通性和服务状态",
            "确认域名、端口和配置是否正确",
        ]
    elif "skipped" in text and "failed" not in text and "error" not in text and "passed" not in text:
        error_type = "skipped_only"
        confidence = 0.95
        evidence.append("pytest summary indicates skipped tests only")
        possible_causes = ["pytest 已收集用例，但这些用例目前被标记为 skip，尚未绑定真实自动化实现"]
        next_actions = [
            "选择 P0 用例优先接入页面/API/DB 自动化动作",
            "将对应 pytest.skip 替换为真实操作和断言",
        ]
    elif "passed" in text and "failed" not in text and "error" not in text:
        error_type = "passed"
        confidence = 0.95
        evidence.append("pytest summary indicates passed")
        possible_causes = ["pytest 执行完成，未发现失败信息"]
        next_actions = ["可以继续整理通过数量、执行时长和关键覆盖范围"]

    failure_locations = _extract_failure_locations(raw_text)
    if failure_locations:
        evidence.extend(failure_locations[:3])
    if _has_meaningful_flaky_signal(raw_text):
        flaky_signals.append("输出中出现 retry/rerun/flaky 线索，需要检查是否为不稳定用例")

    return {
        "_ok": error_type == "passed",
        "_error": "" if error_type == "passed" else error_type,
        "_metadata": {
            "confidence": confidence,
            "failure_location_count": len(failure_locations),
        },
        "task": "result_analysis",
        "error_type": error_type,
        "confidence": confidence,
        "pytest_summary": _extract_pytest_summary(raw_text),
        "evidence": evidence,
        "flaky_signals": flaky_signals,
        "flaky_heuristics": list(FLAKY_TEST_HEURISTICS),
        "failure_locations": failure_locations,
        "summary": raw_text[:500],
        "possible_causes": possible_causes,
        "next_actions": next_actions,
    }
