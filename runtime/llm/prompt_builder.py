# ruff: noqa: E501

from __future__ import annotations

import re
from dataclasses import dataclass

from runtime.llm.config import DEFAULT_MAX_INPUT_CHARS

MAX_INPUT_CHARS = DEFAULT_MAX_INPUT_CHARS
IMAGE_REFERENCE_RE = re.compile(
    r"!\[[^\]]*]\([^)]+\)|\.(?:png|jpe?g)\b|(?:^|[^A-Za-z0-9_])(?:media|images)[\\/]",
    re.IGNORECASE | re.MULTILINE,
)
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")
LONG_IMAGE_URL_RE = re.compile(
    r"https?://[^\s)>\]]*(?:feishu|larksuite|drive|image|media|png|jpe?g)[^\s)>\]]*",
    re.IGNORECASE,
)
DEFAULT_SECTION_BUDGET = 700


@dataclass(frozen=True)
class PromptBuildResult:
    prompt: str
    warnings: list[str]


def _compact_prompt_content(content: str) -> str:
    compacted = MARKDOWN_IMAGE_RE.sub("[图片引用已省略：当前 Runtime 不分析图片内容]", content)
    return LONG_IMAGE_URL_RE.sub("[图片链接已省略]", compacted)


def _section_budget(title_or_path: str, max_input_chars: int) -> int:
    """Bound each context source so one long file cannot crowd out key inputs."""
    capped = max(200, max_input_chars)
    if title_or_path.endswith("/input/requirement.md"):
        return min(6000, capped)
    if title_or_path.endswith("/input/api.md"):
        return min(3000, capped)
    if title_or_path.endswith("/artifacts/requirement-analysis.md"):
        return min(6000, capped)
    if "本次运行" in title_or_path or "需求分析草稿" in title_or_path:
        return min(7000, capped)
    if "RAG" in title_or_path:
        return min(3500, capped)
    if title_or_path == "图片检测":
        return min(1000, capped)
    if title_or_path.endswith("skills/registry/skills.yaml"):
        return min(900, capped)
    if title_or_path.startswith("skills/"):
        return min(DEFAULT_SECTION_BUDGET, capped)
    if title_or_path.startswith("rules/") or title_or_path.startswith("knowledge/templates/"):
        return min(1000, capped)
    if title_or_path.startswith("prompts/"):
        return min(900, capped)
    return min(DEFAULT_SECTION_BUDGET, capped)


def _clip_section(content: str, budget: int) -> str:
    if len(content) <= budget:
        return content
    marker = "\n\n[上下文已按优先级裁剪，省略中间低价值内容]\n\n"
    if budget <= len(marker) + 40:
        return content[:budget]
    head_budget = max(80, int((budget - len(marker)) * 0.7))
    tail_budget = budget - len(marker) - head_budget
    return content[:head_budget].rstrip() + marker + content[-tail_budget:].lstrip()


def _render_section(title: str, content: str, max_input_chars: int) -> str:
    compacted = _compact_prompt_content(content)
    budget = _section_budget(title, max_input_chars)
    return f"## {title}\n\n{_clip_section(compacted, budget)}"


def _render_file_bundle(
    loaded_files: dict[str, str],
    selected_paths: list[str],
    *,
    injected_sections: dict[str, str] | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> tuple[str, list[str]]:
    sections: list[str] = []
    warnings: list[str] = []
    injected_sections = injected_sections or {}

    for path in selected_paths:
        if path in loaded_files:
            sections.append(_render_section(path, loaded_files[path], max_input_chars))

    for title, content in injected_sections.items():
        if content:
            sections.append(_render_section(title, content, max_input_chars))

    bundle = "\n\n".join(sections)
    if len(bundle) > max_input_chars:
        bundle = bundle[:max_input_chars]
        warnings.append(f"LLM Prompt 输入超过 {max_input_chars} 字符，已截断。")
    return bundle, warnings


def _image_detection_section(loaded_files: dict[str, str], prd_prefix: str) -> str:
    requirement = loaded_files.get(f"{prd_prefix}/input/requirement.md", "")
    if not IMAGE_REFERENCE_RE.search(requirement):
        return ""
    return (
        "检测到 input/requirement.md 包含图片/原型图引用。当前 Runtime 不分析图片内容，"
        "只允许基于 input/requirement.md 和 input/api.md 的文本生成草稿。必须把图片内容"
        "未分析写入待确认问题，禁止猜测图片中的字段、按钮、页面布局和交互。"
    )


def _cot_reasoning_instruction() -> str:
    return """## 推理过程（请逐步思考，再输出最终结果）

在输出最终文档之前，请按以下步骤推理（推理过程不写入输出，仅作为内部思考链）：

### 步骤 1：理解输入
- 仔细阅读所有输入材料（需求、接口文档、规则、技能、模板）
- 识别业务领域、用户角色、核心流程
- 标记不确定/缺失的信息

### 步骤 2：分析关键约束
- 有哪些明确的业务规则？
- 有哪些隐含假设需要标记？
- 技术/环境限制是什么？

### 步骤 3：规划输出结构
- 确认所有必须包含的章节
- 确认 Front Matter 格式
- 确保没有遗漏质量要求

### 步骤 4：自检清单
输出完成后，逐项检查：
□ 每个章节都有具体内容，不是模板占位
□ 所有不确定项都标记为"待确认"
□ Front Matter 完整且正确
□ 没有编造需求或规则
□ 满足数量/覆盖要求
□ 输入材料中的每一条信息都已考虑
"""


def _self_check_section() -> str:
    return """## 输出自检清单（生成文档后逐项核对）

### 格式检查
□ Front Matter 完整（status / artifact_type / human_review_required）
□ 所有章节标题与要求一致，无新增/遗漏
□ Markdown 格式正确，表格对齐

### 内容检查
□ 每个章节都有具体分析内容，不是"待补充"或空占位
□ 业务规则、风险点、覆盖映射等关键章节有实质输出
□ 待确认问题具体可回答（不少于 3 个）
□ 假设和不确定处已标记"待确认/待补充/假设"

### 来源检查
□ 所有结论可追溯到输入材料（需求原文、接口文档、已分析文档）
□ 没有编造需求或凭空补充业务规则
□ 图片内容未分析已提示，未猜测图片内容

### 数量检查
□ 用例/分析数量满足最低要求
□ 信息不足时说明了具体缺口，仍输出了可评审内容
"""


def build_requirement_analysis_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    rag_context: str | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/input/requirement.md",
        f"{prd_prefix}/input/api.md",
        "skills/registry/skills.yaml",
        "skills/core/requirement-understanding-skill.md",
        "skills/core/context-building-skill.md",
        "skills/core/rag-retrieval-skill.md",
        "skills/analysis/test-scope-decomposition-skill.md",
        "skills/analysis/risk-identification-skill.md",
        "skills/core/output-formatting-skill.md",
        "rules/requirement-analysis-rules.md",
        "skills/analysis/requirement-decomposition-skill.md",
        "skills/analysis/business-rule-extraction-skill.md",
        "knowledge/templates/requirement-analysis-template.md",
        "prompts/requirement-analysis-prompt.md",
    ]
    injected = {"图片检测": _image_detection_section(loaded_files, prd_prefix)}
    if rag_context:
        injected["RAG 知识库上下文"] = rag_context
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        injected_sections=injected,
        max_input_chars=max_input_chars,
    )
    cot = _cot_reasoning_instruction()
    checklist = _self_check_section()
    prompt = f"""# 系统指令：需求分析生成

你是资深 QA 需求分析 Agent。你的任务是把 PRD 工作区的原始需求拆解成可审核的需求分析草稿。

## 输出格式

必须是 Markdown，并严格包含以下 Front Matter：

---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
---

必须包含且只能以这些章节作为主结构：
## 1. 需求背景与目标
## 2. 业务范围
## 3. 角色与权限
## 4. 主流程拆解
## 5. 分支流程与异常流程
## 6. 业务规则清单
## 7. 数据字段与状态流转
## 8. 接口与依赖系统
## 9. 测试范围建议
## 10. 风险点与影响面
## 11. 待确认问题
## 12. 需求到测试覆盖映射

## 核心质量要求

1. **每章必须结合 PRD 或接口文档输出具体内容**，禁止仅有标题或"待补充"
2. 待确认问题至少 3 个，必须具体可回答（不允许"需求是否明确"这类空话）
3. 业务规则清单、风险点与影响面、需求到测试覆盖映射不得为空或只有"待补充"
4. 每个结论必须可追溯到输入材料
5. 必须说明范围内和范围外能力
6. 假设必须单独标记为"假设"
7. 图片约束：检测到图片引用时，只能基于文本生成分析，禁止猜测图片内容，必须在待确认问题中提示图片内容未分析

## 禁止事项

- 不改写原始需求
- 不凭空补业务规则
- 不输出只有标题和模板占位的空文档
- 不编造需求；不确定内容请标记为"待确认""待补充"或"假设"

{cot}

{checklist}

## 上下文材料

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)


def build_testcase_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    generated_analysis: str | None = None,
    rag_context: str | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/input/requirement.md",
        f"{prd_prefix}/input/api.md",
        "skills/registry/skills.yaml",
        "skills/core/requirement-understanding-skill.md",
        "skills/core/context-building-skill.md",
        "skills/core/rag-retrieval-skill.md",
        "skills/analysis/test-scope-decomposition-skill.md",
        "skills/analysis/risk-identification-skill.md",
        "skills/test-design/test-method-selection-skill.md",
        "skills/test-design/testcase-generation-skill.md",
        "skills/test-design/testcase-review-skill.md",
        "skills/core/output-formatting-skill.md",
        "rules/testcase-rules.md",
        "skills/test-design/test-design-skill.md",
        "skills/test-design/equivalence-partitioning-skill.md",
        "skills/test-design/boundary-value-analysis-skill.md",
        "skills/test-design/scenario-modeling-skill.md",
        "skills/test-design/state-transition-modeling-skill.md",
        "skills/test-design/risk-based-testing-skill.md",
        "knowledge/templates/testcase-template.md",
        "prompts/testcase-design-prompt.md",
    ]
    if not generated_analysis:
        selected_paths.insert(2, f"{prd_prefix}/artifacts/requirement-analysis.md")
    injected = {"图片检测": _image_detection_section(loaded_files, prd_prefix)}
    if generated_analysis:
        injected["本次运行生成的需求分析草稿"] = generated_analysis
    if rag_context:
        injected["RAG 知识库上下文"] = rag_context
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        injected_sections=injected,
        max_input_chars=max_input_chars,
    )
    cot = _cot_reasoning_instruction()
    checklist = _self_check_section()
    prompt = f"""# 系统指令：测试用例生成

你是资深 QA 测试设计 Agent。你的任务是基于需求和分析材料生成可人工审核的测试用例草稿。

## 输出格式

必须是 Markdown，并严格包含以下 Front Matter：

---
status: needs_human_review
artifact_type: testcase_draft
human_review_required: true
---

测试用例主表必须使用列：**用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | 测试步骤 | 预期结果 | 断言/证据 | 待确认项**
不得使用旧 5 列表格（标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果）。
测试类型只能从以下集合选择：正常/规则、异常、边界值、权限/认证、状态流转、幂等/并发、数据一致性、兼容、前后端一致、接口异常、安全/异常、审计/消息、回归、确认/风险。
需求/规则来源必须写清楚来自哪条需求、业务规则、风险点或待确认项；可使用 R01/R02、PRD-段落名、分析-业务规则等可追踪标识。
测试数据必须给出具体数据组合、边界值、用户角色、状态、库存/奖励/邀请关系、分数区间或接口参数；信息缺失时写“待确认：缺少 XXX”，不能留空。
测试数据列禁止写“无”“不适用”“无具体数据”；如果是页面入口类，写具体入口、登录态、设备/浏览器、活动开关；如果是兼容/回归类，写具体设备矩阵、基线版本、回归链路；如果是图片确认类，写等级、图片资源、素材ID或待确认的资源清单。
断言/证据必须覆盖至少两类可观察对象：页面展示、接口响应、数据库/状态、消息/通知、日志/审计、埋点、文件/图片产物。
待确认项必须具体到缺口，例如“待确认：提交接口错误码”“待确认：头像框有效期自然日/工作日口径”，不得写“无”作为所有行的默认值。
只输出一个测试用例主表，不得在主表中间重复表头或分隔行。
所有测试用例优先级必须严格为 P0/P1/P2/P3，不得输出"优先级"、"高"、"中"、"低"等其他值。
禁止输出"占位"、"TODO"、"示例"、"待接入"、"模板"等非用例内容；信息不足时写"待确认"，但仍必须给出可执行步骤和可观察预期结果。

## 覆盖要求（必须全部覆盖）

| 覆盖维度 | 具体要求 |
|---|---|
| 正常流程 | 主成功路径及正常变体 |
| 关键分支 | 主要分支和业务规则差异 |
| 权限与角色 | 未授权、角色差异、数据归属差异 |
| 状态流转 | 创建、处理中、成功、失败、取消、锁定、完成 |
| 必填/格式/边界 | 输入错误、N-1/N/N+1、最小/最大值附近 |
| 异常流程 | 认证失败、状态不允许、依赖失败 |
| 重复提交/幂等 | 重复点击、接口重放、并发提交 |
| 数据一致性 | 错误次数、锁定时间、token 字段一致性 |
| 老数据兼容 | 历史数据、已废弃状态的兼容处理 |
| 前后端一致 | 页面文案、接口码、数据库状态 |
| 接口异常 | 弱网、超时、依赖失败 |
| 回归风险 | 历史高风险和核心 P0 场景 |

## 核心质量要求

1. 简单需求不少于 15 条，中等需求不少于 30 条，复杂需求不少于 50 条
2. 信息不足时必须说明缺口，但仍输出可评审用例
3. 每条用例的前置条件必须说明账号、角色、数据、开关、状态
4. 预期结果应包含页面、接口、数据库、状态、日志或消息等可观察结果
5. 检测到图片时，禁止猜测图片中的字段、按钮、页面布局和交互
6. 可以增加待确认类用例或风险说明，提醒图片内容未覆盖
7. 必须显式覆盖业务规则追踪、测试数据设计、断言证据和待确认缺口，不能只输出通用操作步骤
8. 对边界值用例必须给出具体 N-1/N/N+1 或区间临界值；对奖励/库存/邀请/抽奖必须给出数据组合和去重规则验证

## 禁止事项

- 不输出没有预期结果的用例
- 不把未确认假设当事实
- 不输出"待接入 LangChain 后生成"或少量示例用例
- 不得生成 API/UI 自动化脚本
- 不得输出正式 QA 结论
- 不得输出旧版 5 列表格或缺失“测试数据”“断言/证据”“需求/规则来源”的表格

{cot}

{checklist}

## 上下文材料

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)


def build_api_test_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    rag_context: str | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/input/requirement.md",
        f"{prd_prefix}/input/api.md",
        f"{prd_prefix}/artifacts/requirement-analysis.md",
        f"{prd_prefix}/artifacts/testcases.md",
        "docs/api-test-generation.md",
        "skills/api-testing.md",
        "prompts/api-test-generation.md",
        "rules/review-gate-rules.md",
        "rules/artifact-path-rules.md",
    ]
    injected = {}
    if rag_context:
        injected["RAG 知识库上下文"] = rag_context
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        injected_sections=injected,
        max_input_chars=max_input_chars,
    )
    prompt = f"""# 系统指令：接口测试草稿生成

你是 API 测试设计 Agent。你的任务是根据 PRD、接口文档、需求分析和已确认测试用例生成可审核的接口测试草稿。本阶段只生成计划和 pytest + requests 脚本草稿，不执行真实 HTTP 请求。

## 输出要求

必须是 Markdown，并严格包含 Front Matter：

---
status: needs_human_review
artifact_type: api_test_draft
human_review_required: true
---

必须包含以下章节：
## 1. 接口清单
## 2. 接口测试点矩阵
## 3. 请求示例
## 4. pytest + requests 脚本草稿
## 5. 断言策略
## 6. 测试数据准备建议
## 7. 环境与鉴权待补充项
## 8. 风险与限制

## 核心质量要求

1. 有 input/api.md 时，以接口文档为准，不得凭需求自行改写 URL、Method、字段或错误码。
2. 没有可用 input/api.md 时，只能输出“接口候选点/待补充接口信息”，必须显式写“待补充接口文档”“待确认 URL”“待确认 Method”“待确认请求字段”“待确认响应字段”“待确认鉴权方式”。
3. 断言覆盖 HTTP 状态码、业务 code、message、data 字段，以及 DB/Redis/MQ 校验建议。
4. pytest 脚本只作为草稿，必须使用环境变量读取 base_url、token、Cookie 或密钥，不得硬编码真实敏感信息。
5. 一个测试函数只测一个场景，函数名体现测试目的。
6. 输出必须可追溯到需求、接口文档、需求分析或测试用例。

## 禁止事项

- 不真实调用接口，不输出“已执行 / 执行通过 / 实测通过”等执行结论。
- 不连接真实数据库、Redis 或 MQ。
- 不读取或写入真实 token、Cookie、密钥。
- 不生成 Allure、Jenkins 或线上执行说明。
- 不把推断接口写成确定事实。

## 先思考再输出

在写脚本前，先理解：
1. API 契约：路径、方法、请求体、响应体
2. 哪些字段需要参数化测试
3. 如何构造前置条件（注册/登录/创建数据）
4. 失败场景的预期行为

## 上下文材料

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)


def build_ui_test_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    rag_context: str | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/input/requirement.md",
        f"{prd_prefix}/input/api.md",
        f"{prd_prefix}/artifacts/testcases.md",
        f"{prd_prefix}/artifacts/requirement-analysis.md",
        f"{prd_prefix}/input/ui-flow.md",
        "docs/ui-test-generation.md",
        "skills/ui-testing.md",
        "prompts/ui-test-generation.md",
        "rules/ui-test-rules.md",
        "rules/automation-rules.md",
        "skills/automation/playwright-ui-test-skill.md",
        "knowledge/project-rules/assertion-rules.md",
    ]
    injected = {}
    if rag_context:
        injected["RAG 知识库上下文"] = rag_context
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        injected_sections=injected,
        max_input_chars=max_input_chars,
    )
    prompt = f"""# 系统指令：UI 测试生成

你是 UI 自动化测试 Agent。你的任务是根据需求和用例生成 Playwright UI 自动化草稿。

## 输出要求

输出应包含以下内容：
1. **Playwright 脚本草稿** — 使用 Page Object Model，可执行业务流程
2. **选择器策略** — 优先 data-testid > aria-label > text > CSS class
3. **测试数据和环境说明** — 需要哪些前置数据和配置
4. **不适合自动化的场景说明** — 如验证码、风控、第三方依赖

## 核心质量要求

1. 使用稳定选择器（data-testid 优先），避免 CSS class 依赖
2. 明确等待策略：等待元素可见、可交互，避免固定 sleep
3. 断言清晰：包含页面文案、元素状态、URL 跳转
4. 失败信息明确：每个断言添加自定义失败提示

## 禁止事项

- 不绕过验证码和风控
- 不默认在生产环境执行
- 不使用脆弱选择器（如纯 CSS class 或索引位置）

## 先思考再输出

在写脚本前，先理解：
1. 用户操作的业务流程路径
2. 哪些步骤可以稳定自动化
3. 哪些场景需要手动验证（验证码、生物识别、第三方 OAuth）

## 上下文材料

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)


def build_test_execution_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    rag_context: str | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/metadata.yml",
        f"{prd_prefix}/automation/api/",
        f"{prd_prefix}/automation/ui/",
        "rules/test-execution-rules.md",
        "rules/automation-rules.md",
        "scripts/run_pytest.py",
        "scripts/collect_test_results.py",
        "prompts/test-execution-prompt.md",
    ]
    injected = {}
    if rag_context:
        injected["RAG 知识库上下文"] = rag_context
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        injected_sections=injected,
        max_input_chars=max_input_chars,
    )
    prompt = f"""# 系统指令：测试执行

你是测试执行 Agent。你的任务是在明确授权的环境中执行已审核的测试命令并收集结果。

## 输出要求

输出包含以下内容：
1. **执行命令** — 实际运行的命令
2. **执行环境** — 操作系统、Python 版本、依赖版本
3. **结果文件路径** — 执行产物位置
4. **失败摘要** — 每个失败的测试名称、错误类型、关键错误信息（不贴完整堆栈）
5. **待人工确认项** — 环境是否准确、结果是否可信、失败是否疑似环境问题

## 核心质量要求

1. 结果可追溯：记录命令、时间戳、环境快照
2. 失败不被隐藏：列出全部失败用例，不跳过、不过滤
3. 失败分类提示：区分"可能是环境问题"和"可能是真实缺陷"

## 禁止事项

- 不在未授权环境运行
- 不将失败直接定性为缺陷

## 先思考再输出

在输出前思考：
1. 哪些测试可以并行执行以节省时间？
2. 有哪些已知失败（pre-existing failures）？
3. 环境限制是什么（无 GPU、无外网、无特定端口）？

## 上下文材料

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)


def build_failure_analysis_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    rag_context: str | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/input/requirement.md",
        f"{prd_prefix}/input/api.md",
        f"{prd_prefix}/artifacts/testcases.md",
        f"{prd_prefix}/execution/runs/",
        "rules/failure-analysis-rules.md",
        "rules/test-execution-rules.md",
        "skills/reporting/failure-log-analysis-skill.md",
        "prompts/failure-analysis-prompt.md",
    ]
    injected = {}
    if rag_context:
        injected["RAG 知识库上下文"] = rag_context
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        injected_sections=injected,
        max_input_chars=max_input_chars,
    )
    prompt = f"""# 系统指令：失败分析

你是测试失败分析 Agent。你的任务是把测试执行失败转化为可复核的分类结论、证据链和下一步建议。

## 固定失败分类

| 分类 | 含义 |
|---|---|
| 真实缺陷 | 产品行为与需求/设计不一致 |
| 脚本问题 | 自动化脚本本身有 bug |
| 环境问题 | 测试环境配置、依赖、网络问题 |
| 测试数据问题 | 前置数据不满足或数据冲突 |
| 需求不清 | 需求描述自相矛盾或缺少关键信息 |
| 预期错误 | 测试预期与需求/设计不匹配 |
| 接口文档不一致 | API 实现与文档不一致 |
| 偶现问题 | 无法稳定复现，需要更多信息 |
| 暂无法判断 | 证据不足，需要人工介入 |

## 输出要求和格式

每条失败的分析应包含：
- **失败项** — 测试名称或 ID
- **现象** — 实际失败表现
- **分类** — 从固定分类中选择一个
- **分类依据** — 为什么归为此类
- **证据** — 关键日志片段、断言信息（不贴完整日志）
- **复现建议** — 如何复现或定位根因
- **待人工确认项** — 需要人工判断的内容

## 核心质量要求

1. 使用规定的固定失败分类，不得自定义
2. 证据不足时明确说明"暂无法判断"
3. 每个分类必须有明确的分类依据

## 禁止事项

- 不武断归因为产品缺陷
- 不忽略脚本、环境和数据问题
- 不伪造日志、截图或真实失败证据
- 没有真实日志时，必须输出示例分析框架，不得编造日志内容

## 先思考再输出

分析每个失败按此流程：
1. 现象是什么？（来自执行结果/日志）
2. 是确定性失败还是偶现？
3. 失败发生在前置条件、测试步骤还是断言？
4. 最可能的原因是什么？
5. 哪个分类最匹配？

## 上下文材料

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)


def build_bug_draft_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    rag_context: str | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/input/requirement.md",
        f"{prd_prefix}/input/api.md",
        f"{prd_prefix}/artifacts/testcases.md",
        f"{prd_prefix}/defects/failure-analysis.md",
        "rules/failure-analysis-rules.md",
        "skills/reporting/bug-report-writing-skill.md",
        "knowledge/templates/bug-template.md",
        "prompts/bug-draft-prompt.md",
    ]
    injected = {}
    if rag_context:
        injected["RAG 知识库上下文"] = rag_context
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        injected_sections=injected,
        max_input_chars=max_input_chars,
    )
    prompt = f"""# 系统指令：缺陷草稿生成

你是缺陷报告撰写 Agent。你的任务是把已确认的真实缺陷候选整理为 Markdown 缺陷草稿，供人工转入缺陷系统。

## 输出要求

每个缺陷包含以下字段：
- **缺陷标题** — 简洁描述问题（What + Where + Condition，不超过 30 字）
- **严重程度建议** — P0 阻塞/P1 严重/P2 一般/P3 轻微
- **环境** — 操作系统、浏览器、App 版本、API 版本
- **前置条件** — 需要哪些数据、账号、状态
- **复现步骤** — 明确、无歧义、可执行
- **实际结果** — 当前系统的实际行为
- **预期结果** — 来自需求文档或已确认的业务规则
- **证据** — 日志片段、响应体、错误截图路径（不嵌入图片本身）
- **待确认项** — 是否缺陷、严重程度与优先级、是否可复现

## 核心质量要求

1. 可复现：步骤清晰，前置条件完整
2. 可定位：包含足够证据和关联信息
3. 可转入缺陷系统：格式标准，预期结果有来源
4. 预期结果必须来自需求或已确认规则，不能凭空编造

## 禁止事项

- 不为非产品问题（脚本问题/环境问题/数据问题）生成产品缺陷
- 不夸大严重程度
- 不编造复现步骤

## 先思考再输出

生成每条缺陷前思考：
1. 失败分析中是否确认这是"真实缺陷"分类？
2. 复现步骤是否完整？是否有缺失前置条件？
3. 预期结果是否有明确来源？

## 上下文材料

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)


def build_report_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    rag_context: str | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/metadata.yml",
        f"{prd_prefix}/artifacts/requirement-analysis.md",
        f"{prd_prefix}/artifacts/testcases.md",
        f"{prd_prefix}/execution/runs/",
        f"{prd_prefix}/defects/failure-analysis.md",
        f"{prd_prefix}/defects/bug-drafts/",
        "skills/reporting/qa-report-writing-skill.md",
        "knowledge/templates/qa-report-template.md",
        "prompts/report-generation-prompt.md",
    ]
    injected = {}
    if rag_context:
        injected["RAG 知识库上下文"] = rag_context
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        injected_sections=injected,
        max_input_chars=max_input_chars,
    )
    prompt = f"""# 系统指令：QA 报告生成

你是 QA 报告生成 Agent。你的任务是汇总所有 QA 产物，生成清晰披露测试范围、执行概况、风险和未覆盖项的 QA 报告草稿。

## 输出格式

- 文件路径：`prd/<id>/artifacts/qa-report.md`
- `qa-review.md` 是 AI 生成草稿；最终 `qa-report.md` 由人工确认后生成
- 包含以下章节：
  1. **基本信息** — 需求名称、版本、测试时间、测试范围概述
  2. **产物索引** — 各阶段产出物路径和状态
  3. **测试范围** — 已测/未测功能清单
  4. **执行概况** — 总计/通过/失败/跳过数、通过率
  5. **缺陷和风险** — 按严重程度汇总，关键风险说明
  6. **未覆盖范围** — 计划未覆盖的原因
  7. **结论草稿** — 质量评估草稿、发布建议
  8. **待人工确认项** — 需要人工确认的结论

## 核心质量要求

1. 报告内容可追溯，每个数据点标注来源
2. 风险和限制必须披露，不得隐瞒已知问题
3. 不得伪造执行结果、通过率或缺陷数量
4. 只写结构化摘要、统计和关键风险，不大段复制上游原文

## 禁止事项

- 不输出未经确认的正式发布结论
- 不生成 `qa-report.md`（只生成草稿）
- 不粘贴完整测试用例表、完整需求分析或完整执行日志

## 先思考再输出

生成前思考：
1. 有哪些数据可用？是否有缺失？
2. 通过/失败/跳过数据是否自洽？
3. 最大的风险是什么？
4. 发布建议的措辞是否恰当（草稿级别）？

## 上下文材料

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)


def build_archive_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    rag_context: str | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/metadata.yml",
        f"{prd_prefix}/artifacts/qa-report.md",
        "rules/archive-rules.md",
        "rules/status-rules.md",
        "scripts/archive_requirement.py",
        "prompts/archive-prompt.md",
    ]
    injected = {}
    if rag_context:
        injected["RAG 知识库上下文"] = rag_context
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        injected_sections=injected,
        max_input_chars=max_input_chars,
    )
    prompt = f"""# 系统指令：归档检查与执行

你是归档 Agent。你的任务是在所有人工审核和确认完成后，检查审核状态并生成归档索引。

## 输出要求

输出包含以下内容：
1. **归档检查结果** — 通过/阻塞
2. **阻塞项列表** — 列出所有未完成的审核状态或未解决的缺陷
3. **归档索引路径** — 归档产物清单

## 归档检查清单

检查以下所有项是否完成，任何一项未完成即阻塞归档：
- [ ] 需求分析已审核通过（status 为 approved）
- [ ] 测试用例已审核通过
- [ ] 测试执行已完成且通过率达到约定阈值
- [ ] 所有 P0 缺陷已解决或已确认风险
- [ ] QA 报告草稿已审核
- [ ] 无阻塞状态存在

## 核心质量要求

1. 严格检查阻塞状态，不得绕过
2. 存在阻塞状态时必须拒绝归档并列出具体阻塞项
3. 不删除历史产物，归档只增加索引

## 禁止事项

- 不绕过人工审核
- 不伪造状态
- 不删除或修改已有产物

## 先思考再输出

输出前检查：
1. metadata 和 QA 报告中的审核状态是什么？
2. 是否存在 P0 未解决的缺陷？
3. 是否所有必要产物都已生成并审核？

## 上下文材料

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)
