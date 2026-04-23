from __future__ import annotations

import re
from typing import Any

TEXT_LINE_LIMIT = 220
QUESTION_MARKERS = ("是否", "?", "？", "待确认", "待补充", "tbd", "todo")
RULE_MARKERS = (
    "必须",
    "只能",
    "仅",
    "不可",
    "不能",
    "需要",
    "应",
    "支持",
    "如果",
    "当",
    "默认",
    "实时",
    "自动",
    "after",
    "before",
)
CONSTRAINT_MARKERS = (
    "上限",
    "下限",
    "最多",
    "至少",
    "必填",
    "为空",
    "重复",
    "超时",
    "失败",
    "异常",
    "权限",
    "审核",
    "冻结",
    "解冻",
    "扣罚",
    "提现",
    "缴纳",
)
BUSINESS_VERBS = (
    "显示",
    "展示",
    "支持",
    "跳转",
    "计算",
    "审核",
    "缴纳",
    "补缴",
    "提现",
    "冻结",
    "解冻",
    "扣罚",
    "配置",
    "保存",
    "提交",
    "提示",
    "提醒",
    "生成",
    "选择",
    "输入",
    "查看",
    "查询",
    "导出",
    "修改",
    "新增",
    "删除",
    "关联",
    "带出",
    "下架",
    "退回",
)
SKIP_EXACT = {
    "文档信息",
    "项目",
    "内容",
    "文档名称",
    "文档版本",
    "创建日期",
    "最后更新",
    "文档状态",
    "变更说明",
    "产品经理",
    "技术负责人",
    "在线文档",
    "文档概述",
    "文档目的",
    "适用范围",
    "核心目标",
}
SKIP_CONTAINS = (
    "http://",
    "https://",
    "PRD（飞书）",
    "文档名称",
    "文档版本",
    "创建日期",
    "最后更新",
)
FOCUS_STOPWORDS = {
    "帮我",
    "请",
    "分析",
    "需求",
    "生成",
    "测试",
    "用例",
    "输出",
    "结合",
    "看看",
    "原型",
    "原型图",
    "文档",
    "prd",
    "PRD",
    "markdown",
    "表格",
}


def normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _clean_candidate(line: str) -> str:
    cleaned = re.sub(r"^\s*(?:[-*+]\s+|#{1,6}\s*|\d+[.)、]\s*)", "", line).strip()
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"^(?:功能描述|核心功能|业务规则|字段定义|账户信息展示)[:：]\s*", "", cleaned)
    cleaned = cleaned.strip("|").strip()
    return cleaned.rstrip("。；;!?！？")


def _is_table_separator(line: str) -> bool:
    cleaned = line.replace("|", "").replace("-", "").replace(":", "").strip()
    return cleaned == ""


def _is_heading(line: str) -> bool:
    return line.lstrip().startswith("#")


def _is_noise(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    if cleaned in SKIP_EXACT:
        return True
    if any(token in cleaned for token in SKIP_CONTAINS):
        return True
    if re.fullmatch(r"v?\d+(?:\.\d+)*", cleaned.lower()):
        return True
    if re.fullmatch(r"\d{4}-\d{1,2}(?:-\d{1,2})?", cleaned):
        return True
    if re.fullmatch(r"[-—_]+", cleaned):
        return True
    return False


def _looks_like_requirement(text: str, from_structured_line: bool) -> bool:
    if _is_noise(text):
        return False
    if len(text) > TEXT_LINE_LIMIT:
        return False
    if any(marker in text for marker in QUESTION_MARKERS + RULE_MARKERS + CONSTRAINT_MARKERS):
        return True
    if from_structured_line and any(verb in text for verb in BUSINESS_VERBS):
        return True
    return False


def _extract_focus_terms(user_text: str) -> list[str]:
    normalized = user_text
    for stopword in FOCUS_STOPWORDS:
        normalized = normalized.replace(stopword, " ")
    raw_terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_-]{3,}", normalized)
    terms: list[str] = []
    for term in raw_terms:
        cleaned = term.strip()
        if not cleaned or cleaned in FOCUS_STOPWORDS:
            continue
        terms.append(cleaned)
        if len(cleaned) >= 4:
            for chunk_size in (4, 3, 2):
                for index in range(0, len(cleaned) - chunk_size + 1):
                    chunk = cleaned[index:index + chunk_size]
                    if chunk not in FOCUS_STOPWORDS:
                        terms.append(chunk)
    return _unique(sorted(terms, key=len, reverse=True))


def _select_relevant_sections(text: str, user_text: str) -> str:
    focus_terms = _extract_focus_terms(user_text)
    if not focus_terms:
        return text

    lines = text.splitlines()
    selected: list[str] = []
    current: list[str] = []
    current_level = 0
    capture = False

    for line in lines:
        heading = re.match(r"^(#{1,6})\s*(.+)$", line.strip())
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            if capture and level <= current_level:
                selected.extend(current)
                current = []
                capture = False
            if any(term in title for term in focus_terms):
                capture = True
                current_level = level
                current = [line]
                continue

        if capture:
            current.append(line)

    if capture:
        selected.extend(current)

    if selected:
        return "\n".join(selected)

    matched_lines = [line for line in lines if any(term in line for term in focus_terms)]
    if matched_lines:
        return "\n".join(matched_lines)

    return text


def _extract_table_candidate(line: str) -> str:
    if line.count("|") < 2 or _is_table_separator(line):
        return ""
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    cells = [cell for cell in cells if cell and not _is_noise(cell)]
    if len(cells) <= 1:
        return ""
    return " / ".join(cells)


def extract_requirement_items_from_text(text: str, limit: int = 80) -> list[str]:
    candidates: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```") or _is_table_separator(line):
            continue

        table_candidate = _extract_table_candidate(line)
        if table_candidate and _looks_like_requirement(table_candidate, from_structured_line=True):
            candidates.append(table_candidate)
            continue

        if _is_heading(line):
            continue

        cleaned = _clean_candidate(line)
        if _looks_like_requirement(cleaned, from_structured_line=raw_line.lstrip() != raw_line):
            candidates.append(cleaned)

    if not candidates:
        sentences = re.split(r"[。；;!?！？\n]+", text)
        for sentence in sentences:
            cleaned = normalize_text(sentence)
            if _looks_like_requirement(cleaned, from_structured_line=False):
                candidates.append(cleaned)

    return _unique(candidates)[:limit]


def extract_requirement_items(user_text: str, requirement_context: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for document in requirement_context.get("selected_requirement_docs", []):
        content = document.get("content", "")
        if content:
            relevant_content = _select_relevant_sections(content, user_text)
            items.extend(extract_requirement_items_from_text(relevant_content))

    if not items:
        items.extend(extract_requirement_items_from_text(user_text))

    return _unique(items)


def split_questions(items: list[str]) -> tuple[list[str], list[str]]:
    requirement_items: list[str] = []
    open_questions: list[str] = []
    for item in items:
        normalized_item = item.strip().rstrip("。；;!?！？")
        lowered = normalized_item.lower()
        if any(marker in lowered for marker in QUESTION_MARKERS):
            open_questions.append(normalized_item)
        else:
            requirement_items.append(normalized_item)
    return requirement_items, open_questions


def derive_business_rules(items: list[str]) -> list[str]:
    rules = [item for item in items if any(marker in item for marker in RULE_MARKERS + CONSTRAINT_MARKERS)]
    return _unique(rules or items)


def derive_risks(items: list[str]) -> list[str]:
    risks: list[str] = []
    for item in items:
        if any(marker in item for marker in ("必须", "仅", "只能", "不能", "不可", "权限")):
            risks.append(f"如果约束“{item}”没有被严格实现，容易出现逻辑偏差、权限问题或合规风险")
        if any(marker in item for marker in ("超时", "失败", "异常")):
            risks.append(f"如果“{item}”的异常分支未覆盖，容易出现失败后无兜底或状态不一致")
        if any(marker in item for marker in ("重复", "幂等")):
            risks.append(f"如果“{item}”的重复触发未处理，容易产生重复数据或重复动作")
        if any(marker in item for marker in ("上限", "下限", "最多", "至少", "为空", "必填")):
            risks.append(f"如果“{item}”的边界约束未校验，容易出现脏数据或错误结果")
        if any(marker in item for marker in ("冻结", "解冻", "扣罚", "提现", "缴纳")):
            risks.append(f"“{item}”涉及资金或余额状态变化，需要重点验证金额、状态、流水和权限一致性")
    return _unique(risks)


def derive_test_focus(items: list[str]) -> list[str]:
    focus = [f"验证需求项：{item}" for item in items]
    for item in items:
        if any(marker in item for marker in ("如果", "当", "失败", "异常", "超时")):
            focus.append(f"验证分支处理：{item}")
        if any(marker in item for marker in ("上限", "下限", "最多", "至少", "为空", "必填")):
            focus.append(f"验证边界条件：{item}")
        if any(marker in item for marker in ("重复", "幂等")):
            focus.append(f"验证重复执行：{item}")
        if any(marker in item for marker in ("冻结", "解冻", "扣罚", "提现", "缴纳")):
            focus.append(f"验证资金链路：{item}")
    return _unique(focus)
