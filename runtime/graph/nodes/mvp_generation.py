# ruff: noqa: E501

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rag.config import RagConfig
from rag.manager import RagManager
from rag.retriever import assemble_rag_context
from runtime.config import load_app_config
from runtime.graph.nodes.mvp_context_loader import (
    TASK_ANALYSIS,
    TASK_MVP,
    TASK_TESTCASE_GENERATION,
)
from runtime.graph.state import QAWorkflowState
from runtime.llm.config import OpenAICompatibleConfig
from runtime.llm.openai_compatible import OpenAICompatibleAdapter
from runtime.llm.prompt_builder import (
    build_requirement_analysis_prompt,
    build_testcase_prompt,
)


@dataclass(frozen=True)
class RequirementContext:
    prd_prefix: str
    title: str
    requirement: str
    api_doc: str
    metadata: str
    background: str
    scope_items: list[str]
    out_of_scope_items: list[str]
    acceptance_items: list[str]
    pending_items: list[str]
    endpoints: list[str]
    fields: list[str]
    requirement_has_images: bool


def _prd_prefix(state: QAWorkflowState) -> str:
    return state.prd_path.replace("\\", "/").rstrip("/")


def _build_rag_context(state: QAWorkflowState) -> str:
    repo_root = Path.cwd()
    app_config = load_app_config(repo_root)
    config = RagConfig.from_app_config(app_config.rag)
    if not config.enabled:
        return ""
    try:
        query = _build_rag_query(state)
        manager = RagManager(repo_root, config)
        retrieval = manager.retrieve(query or state.user_input)
        state.rag_retrievals.append(
            {
                "node": state.executed_nodes[-1] if state.executed_nodes else "",
                **retrieval.to_trace(),
            }
        )
        context = assemble_rag_context(retrieval, max_chars=4000)
    except Exception as exc:
        state.warnings.append(f"RAG 召回失败，已降级为无 RAG 上下文: {exc}")
        return ""
    if context:
        state.warnings.append("已通过 RAG 召回测试规范、Prompt 模板和项目文档上下文。")
    return context


RAG_QUERY_KEYWORDS = (
    "规则",
    "边界",
    "状态",
    "流程",
    "异常",
    "风险",
    "字段",
    "接口",
    "权限",
    "奖励",
    "邀请",
    "分享",
    "测试",
    "用例",
)


def _build_rag_query(state: QAWorkflowState, *, max_chars: int = 6000) -> str:
    """构造面向知识库检索的查询摘要，而不是直接嵌入整篇 PRD。"""
    sections: list[str] = [state.user_input]
    for key, value in state.loaded_files.items():
        if not key.endswith(("input/requirement.md", "input/api.md", "requirement-analysis.md")):
            continue
        selected: list[str] = []
        for line in value.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                selected.append(stripped)
                continue
            if any(keyword in stripped for keyword in RAG_QUERY_KEYWORDS):
                selected.append(stripped)
            if len("\n".join(selected)) >= max_chars // 2:
                break
        if selected:
            sections.append(f"## {key}\n" + "\n".join(selected))
    query = "\n\n".join(sections)
    return query[:max_chars]


def _path_content(state: QAWorkflowState, suffix: str) -> str:
    prd_prefix = _prd_prefix(state)
    return state.loaded_files.get(f"{prd_prefix}/{suffix}", "")


def _metadata_value(metadata: str, key: str) -> str | None:
    for line in metadata.splitlines():
        if line.startswith(f"{key}:"):
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def _first_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line.lstrip("#").strip()
    return None


def _section(markdown: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    return match.group("body").strip() if match else ""


def _bullets(markdown: str) -> list[str]:
    items: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            value = stripped[2:].strip()
            if value:
                items.append(value)
    return items


def _paragraph_summary(markdown: str, *, fallback: str) -> str:
    lines = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-", "*", "|", "```")):
            continue
        lines.append(stripped)
        if len("".join(lines)) >= 160:
            break
    return " ".join(lines) if lines else fallback


def _api_endpoints(api_doc: str) -> list[str]:
    endpoints = []
    for match in re.finditer(r"^##\s+([A-Z]{3,7})\s+([^\s]+)", api_doc, re.MULTILINE):
        endpoints.append(f"{match.group(1)} {match.group(2)}")
    return endpoints


def _json_fields(*contents: str) -> list[str]:
    fields: list[str] = []
    for content in contents:
        for match in re.finditer(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', content):
            field_name = match.group(1)
            if field_name not in fields:
                fields.append(field_name)
    return fields


def _first_non_empty(items: list[str], fallback: str) -> str:
    return items[0] if items else fallback


def _format_bullets(items: list[str], fallback: str) -> str:
    values = items or [fallback]
    return "\n".join(f"- {item}" for item in values)


def _format_numbered(items: list[str], fallback: str) -> str:
    values = items or [fallback]
    return "\n".join(f"{index}. {item}" for index, item in enumerate(values, start=1))


def _build_requirement_context(state: QAWorkflowState) -> RequirementContext:
    requirement = _path_content(state, "input/requirement.md")
    api_doc = _path_content(state, "input/api.md")
    metadata = _path_content(state, "workspace.yml")
    title = (
        _metadata_value(metadata, "title")
        or _first_heading(requirement)
        or "未命名业务需求"
    )
    pending_items = [
        *_bullets(_section(requirement, "待人工审核")),
        *_bullets(_section(requirement, "待确认项")),
        *_bullets(_section(api_doc, "待确认项")),
        *_bullets(_section(api_doc, "待人工审核")),
    ]
    return RequirementContext(
        prd_prefix=_prd_prefix(state),
        title=title,
        requirement=requirement,
        api_doc=api_doc,
        metadata=metadata,
        background=_paragraph_summary(
            _section(requirement, "背景"),
            fallback="PRD 未单独提供背景段落，以下分析基于功能范围和验收标准拆解。",
        ),
        scope_items=_bullets(_section(requirement, "功能范围")),
        out_of_scope_items=_bullets(_section(requirement, "非目标范围")),
        acceptance_items=_bullets(_section(requirement, "验收标准")),
        pending_items=pending_items,
        endpoints=_api_endpoints(api_doc),
        fields=_json_fields(requirement, api_doc),
        requirement_has_images=bool(state.prototype_notes.get("requirement_has_images")),
    )


def _is_login_context(context: RequirementContext) -> bool:
    combined = f"{context.title}\n{context.requirement}\n{context.api_doc}"
    return all(keyword in combined for keyword in ("手机号", "密码")) and "token" in combined


def _render_source_files(state: QAWorkflowState) -> str:
    return "\n".join(f"- `{path}`" for path in sorted(state.loaded_files))


def _render_business_rules(context: RequirementContext) -> str:
    rules = [*context.scope_items, *context.acceptance_items]
    if not rules:
        rules = [
            "主流程必须按 PRD 正文描述完成，输入、处理结果和页面反馈需保持一致。",
            "权限、角色、数据归属、活动开关和状态流转规则需产品补充确认后纳入测试。",
            "接口错误码、奖励发放、库存/次数、时间窗口和日志审计口径需人工确认。",
        ]

    rows = []
    for index, rule in enumerate(rules, start=1):
        source = "`input/requirement.md`"
        rows.append(
            f"| R{index:02d} | {rule} | {source} | needs_human_review |"
        )

    if context.endpoints:
        for endpoint in context.endpoints:
            rows.append(
                f"| R{len(rows) + 1:02d} | 接口 `{endpoint}` 的请求、响应和错误码"
                "必须与需求规则一致 | `input/api.md` | needs_human_review |"
            )

    return "\n".join(
        [
            "| 编号 | 规则 | 来源 | 状态 |",
            "|---|---|---|---|",
            *rows,
        ]
    )


def _render_mapping_rows(context: RequirementContext) -> str:
    source_rules = context.scope_items or context.acceptance_items
    if not source_rules:
        source_rules = [f"{context.title} 核心业务流程"]

    rows = []
    for index, rule in enumerate(source_rules, start=1):
        priority = "P0" if index <= 3 else "P1"
        rows.append(
            f"| {rule} | 主流程、分支流程、异常/边界、权限/状态、数据一致性 | {priority} |"
        )
    rows.extend(
        [
            "| 权限、认证或角色差异 | 未授权、越权、角色可见性和可编辑性 | P0/P1 |",
            "| 重复提交、并发和幂等 | 防重、状态重复流转、数据不重复落库 | P1 |",
            "| 依赖系统和接口异常 | 弱网、超时、上游失败、前后端展示一致性 | P1/P2 |",
        ]
    )
    return "\n".join(rows)


IMAGE_PENDING_QUESTION = (
    "需求文档包含图片/原型图引用，但当前 Runtime 未分析图片内容；请确认图片中"
    "是否存在字段、按钮、状态、弹窗、权限差异或交互规则未写入正文。"
)


def _image_analysis_note(context: RequirementContext) -> str:
    if context.requirement_has_images:
        return (
            "- 待确认：需求文档包含图片/原型图引用；当前 Runtime 不分析图片内容，"
            "只基于 input/requirement.md 和 input/api.md 的文本生成草稿。"
        )
    return ""


def _image_pending_questions(context: RequirementContext) -> list[str]:
    if context.requirement_has_images:
        return [
            IMAGE_PENDING_QUESTION,
            "是否允许本次 QA 草稿仅覆盖需求正文和接口文档中已经写明的业务规则？",
            "图片中若存在未写入正文的业务信息，是否需要先补充到 input/requirement.md 后再评审？",
        ]
    return []


def _image_branch_row(context: RequirementContext) -> str:
    if not context.requirement_has_images:
        return ""
    return "| 图片内容未分析 | input/requirement.md 包含图片/原型图引用 | 当前不读取图片内容，图片中的字段、按钮、状态、弹窗、权限差异或交互规则需人工确认 |"


def _image_data_row(context: RequirementContext) -> str:
    if not context.requirement_has_images:
        return ""
    return "| 图片/原型图引用 | 当前 Runtime 不分析图片内容 | 不把图片中的字段、按钮、布局或交互当成已知事实 |"


def _image_risk_row(context: RequirementContext) -> str:
    if not context.requirement_has_images:
        return ""
    return "| 图片内容被忽略 | 图片中的字段、按钮、状态、弹窗、权限差异或交互规则可能未覆盖 | 人工确认图片信息是否已写入 input/requirement.md |"


def _render_login_analysis(context: RequirementContext, source_lines: str) -> str:
    endpoints = _format_bullets(
        [f"`{endpoint}`" for endpoint in context.endpoints],
        "PRD 未提供接口路径，待接口负责人补充登录和受保护资源接口。",
    )
    fields = ", ".join(context.fields or ["phone", "password", "access_token", "expires_in"])
    pending = _format_bullets(
        [
            *(
                context.pending_items
                or [
                    "锁定计数维度需确认是账号、手机号、设备、IP 还是组合维度。",
                    "锁定剩余时间字段名、单位和是否必须返回需接口负责人确认。",
                    "token 有效期、刷新策略和服务端失效策略需安全负责人确认。",
                ]
            ),
            *_image_pending_questions(context),
        ],
        "待确认：PRD 未列出待确认项。",
    )
    scope = _format_bullets(context.scope_items, "手机号密码登录、锁定、token 返回和过期访问控制。")
    out_of_scope = _format_bullets(
        context.out_of_scope_items,
        "注册、找回密码、短信验证码登录、多因素认证和具体加密算法未在本次范围内。",
    )
    acceptance = _format_bullets(
        context.acceptance_items,
        "登录成功、密码错误、账号锁定、token 返回和 token 过期均需满足验收。",
    )
    return f"""---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
generated_by: Runtime MVP Review Grade Draft
---

# 需求分析草稿

## 1. 需求背景与目标

- 背景：{context.background}
- 目标：支持用户通过中国大陆手机号和密码完成登录，登录成功后获得 Bearer token，并在 token 过期后引导重新登录。
- 验收依据：
{acceptance}

## 2. 业务范围

**范围内**

{scope}

**范围外**

{out_of_scope}

## 3. 角色与权限

| 角色 | 权限/动作 | 限制与待确认 |
|---|---|---|
| 未登录用户 | 输入手机号和密码发起登录 | 只能访问登录入口，不能访问受保护资源 |
| 已登录用户 | 携带 `Authorization: Bearer <token>` 访问受保护资源 | token 过期后必须重新登录 |
| 认证服务 | 校验手机号格式、密码、错误次数、锁定状态并签发 token | 锁定计数维度和 token 失效策略待确认 |
| 产品/安全/后台角色 | 确认错误文案、锁定策略、token 有效期和审计要求 | PRD 未定义后台配置入口，默认不在本次实现范围 |

{_image_analysis_note(context)}

## 4. 主流程拆解

1. 用户打开登录入口并输入手机号、密码。
2. 客户端或服务端校验手机号是否符合中国大陆手机号格式。
3. 服务端查询账号状态，确认账号未处于锁定期。
4. 服务端校验密码；校验通过后清理或保持错误计数策略需待确认。
5. 服务端返回 `access_token`、`token_type` 和 `expires_in`。
6. 客户端后续访问受保护资源时携带 Bearer token。
7. token 过期后访问受保护资源返回重新登录提示。

## 5. 分支流程与异常流程

| 场景 | 触发条件 | 预期处理 |
|---|---|---|
| 手机号格式错误 | 手机号为空、长度不符或不符合大陆手机号格式 | 拒绝登录，返回 `INVALID_PHONE` 或等价错误 |
| 密码错误未达阈值 | 同一计数维度连续错误次数小于 5 | 返回“手机号或密码错误”，不得泄露账号是否存在 |
| 第 5 次密码错误 | 连续错误达到 5 次 | 账号进入 15 分钟锁定状态 |
| 锁定期间登录 | 锁定未到期，用户再次登录 | 返回 `ACCOUNT_LOCKED`，不签发 token，并提示剩余锁定时间规则待确认 |
| token 过期访问资源 | Bearer token 已过期 | 返回 `TOKEN_EXPIRED`，提示重新登录 |
| 接口协议差异 | HTTP 状态码与业务码实现不一致 | 进入待确认，不自行裁决 |
{_image_branch_row(context)}

## 6. 业务规则清单

{_render_business_rules(context)}

## 7. 数据字段与状态流转

| 数据/状态 | 规则 | 测试关注点 |
|---|---|---|
| `{fields}` | 登录请求、响应和受保护资源访问相关字段 | 字段必填、格式、缺失、类型和前后端展示一致性 |
| 正常账号 | 可使用正确密码登录 | 成功后返回 token，错误计数策略待确认 |
| 错误计数中 | 密码错误次数累计但未达 5 次 | 第 1 至第 4 次均不应锁定 |
| 锁定中 | 连续错误达到 5 次后锁定 15 分钟 | 锁定期间正确密码也不能登录 |
| 锁定解除 | 锁定超过 15 分钟 | 是否自动解除、是否重置错误计数待确认 |
| token 有效 | 可访问受保护资源 | Authorization 格式和 token_type 一致 |
| token 过期 | 访问受保护资源需重新登录 | 返回码、文案和客户端跳转一致 |
{_image_data_row(context)}

## 8. 接口与依赖系统

{endpoints}

- 依赖账号/会员系统校验用户存在性、密码和账号状态。
- 依赖认证/token 服务签发和校验 Bearer token。
- 依赖受保护资源接口验证 token 过期处理。
- 依赖日志/审计系统记录失败登录、锁定和高风险访问，是否必须记录待确认。

## 9. 测试范围建议

- P0：登录成功、密码错误安全文案、第 5 次锁定、锁定期间拒绝登录、token 过期访问控制。
- P1：手机号必填/格式/边界、锁定解除、重复提交、并发错误计数、数据一致性。
- P2：弱网、超时、依赖失败、历史账号状态、前后端展示一致性、日志审计。
- 不执行真实测试，不生成 API/UI 自动化脚本；本阶段只生成待人工审核草稿。

## 10. 风险点与影响面

| 风险点 | 影响面 | 建议处理 |
|---|---|---|
| 锁定计数维度不明确 | 安全策略、测试数据和误锁风险 | 产品/安全确认账号、手机号、设备、IP 维度 |
| 错误文案泄露账号状态 | 账号枚举风险和合规风险 | 统一错误文案并验证不存在账号与错误密码一致 |
| token 有效期和刷新策略不明确 | 登录态、客户端体验和安全风险 | 明确 expires_in、刷新和服务端失效策略 |
| 并发错误计数 | 可能绕过 5 次锁定或提前锁定 | 设计并发和幂等验证 |
| 前后端状态不一致 | 页面提示、接口码和数据库状态不一致 | 校验页面、接口、状态和日志一致 |
{_image_risk_row(context)}

## 11. 待确认问题

{pending}

## 12. 需求到测试覆盖映射

| 需求/规则 | 测试覆盖建议 | 优先级 |
|---|---|---|
{_render_mapping_rows(context)}

## 来源文件

{source_lines}
"""


def _render_generic_analysis(context: RequirementContext, source_lines: str) -> str:
    scope = _format_bullets(
        context.scope_items,
        f"{context.title} 的核心业务操作、规则校验、状态更新和结果反馈。",
    )
    out_of_scope = _format_bullets(
        context.out_of_scope_items,
        "PRD 未明确列出非目标范围，需产品确认本需求是否排除后台配置、历史数据迁移、消息通知和自动化脚本。",
    )
    acceptance = _format_bullets(
        context.acceptance_items,
        "PRD 未条目化验收标准，需产品补充可验证的成功、失败、边界和状态验收口径。",
    )
    endpoints = _format_bullets(
        [f"`{endpoint}`" for endpoint in context.endpoints],
        "PRD 未提供接口文档，待补充接口路径、请求参数、响应字段、错误码和依赖系统。",
    )
    fields = ", ".join(context.fields) if context.fields else "核心业务字段待从接口文档补充"
    pending_items = [
        *(
            context.pending_items
            or [
                "核心状态枚举、允许流转方向和终态是否可逆需产品/开发确认。",
                "重复提交、并发处理和幂等键策略需开发确认。",
                "前端提示、接口错误码和日志审计字段需产品/接口负责人确认。",
            ]
        ),
        *_image_pending_questions(context),
    ]
    pending = _format_bullets(pending_items, "待确认：PRD 未列出待确认项。")
    return f"""---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
generated_by: Runtime MVP Review Grade Draft
---

# 需求分析草稿

## 1. 需求背景与目标

- 需求名称：{context.title}
- 背景：{context.background}
- 目标：将 PRD 中的业务动作、规则校验、状态流转、接口依赖和风险点拆解为可评审、可测试的 QA 草稿。
- 验收依据：
{acceptance}

## 2. 业务范围

**范围内**

{scope}

**范围外**

{out_of_scope}

## 3. 角色与权限

| 角色 | 权限/动作 | 限制与待确认 |
|---|---|---|
| 业务用户 | 发起 `{context.title}` 相关业务操作并查看处理结果 | 账号状态、数据归属和可见性规则需确认 |
| 后台/运营角色 | 如需求涉及，可审核、配置或干预业务数据 | PRD 未说明时不得默认开放后台能力 |
| 系统服务 | 执行接口校验、状态更新、消息/日志/审计写入 | 依赖失败、重试和幂等策略需确认 |
| 审核/财务/风控角色 | 如涉及金额、库存、优惠、结算或高风险操作需参与确认 | 角色差异需在用例中单独覆盖 |

{_image_analysis_note(context)}

## 4. 主流程拆解

1. 业务用户进入功能入口并准备必要数据。
2. 前端进行必填、格式和基础边界校验。
3. 后端校验权限、数据归属、业务开关和当前状态。
4. 后端根据 PRD 规则创建或更新业务记录，并返回处理结果。
5. 前端展示成功结果、关键状态和后续可操作入口。
6. 系统按需求写入日志、消息、通知或审计记录；如 PRD 未说明则列入待确认。

## 5. 分支流程与异常流程

| 场景 | 触发条件 | 预期处理 |
|---|---|---|
| 必填缺失 | 关键字段为空 | 阻断提交并给出明确错误提示 |
| 格式或边界错误 | 字段格式、金额、数量、时间或次数超出范围 | 返回可识别错误，不产生脏数据 |
| 权限不足 | 非授权角色或非数据归属用户访问 | 拒绝操作并记录必要审计 |
| 状态不允许 | 数据处于已取消、已失效、已完成或不可编辑状态 | 阻断状态流转，保持原状态 |
| 重复/并发提交 | 用户重复点击、接口重放或并发请求 | 保持幂等，不重复扣减、发放、结算或通知 |
| 依赖失败 | 商品、订单、支付、库存、优惠、会员、消息等依赖异常 | 明确失败原因，支持重试或补偿策略待确认 |
{_image_branch_row(context)}

## 6. 业务规则清单

{_render_business_rules(context)}

## 7. 数据字段与状态流转

| 数据/状态 | 规则 | 测试关注点 |
|---|---|---|
| {fields} | PRD/API 中出现的核心字段 | 必填、类型、格式、边界、默认值和前后端一致性 |
| 新建/初始化 | 业务记录首次创建或进入初始态 | 初始化字段、创建人、时间和可见性 |
| 处理中/待审核 | 需要后续校验、审核或依赖返回 | 可编辑性、重复提交和超时处理 |
| 成功/完成 | 主流程处理成功 | 状态终态、消息、日志和后续入口 |
| 失败/拒绝/取消/失效 | 异常或人工操作导致终止 | 原因记录、可恢复性和用户提示 |
| 历史数据 | 老版本字段缺失或状态枚举差异 | 兼容展示、筛选、编辑和接口返回 |
{_image_data_row(context)}

## 8. 接口与依赖系统

{endpoints}

- 可能依赖商品、订单、支付、优惠券、库存、会员、消息、结算、埋点或审计系统；实际依赖以 PRD/API 为准。
- 若接口文档缺失，需补充请求方法、路径、参数、响应字段、错误码、鉴权方式和超时重试策略。

## 9. 测试范围建议

- P0：主成功路径、关键权限阻断、核心状态流转和数据一致性。
- P1：必填、格式、边界、异常流程、重复提交、并发、前后端一致性和回归影响。
- P2：弱网、超时、依赖失败、老数据兼容、日志/消息/审计。
- 不执行真实测试，不生成 API/UI 自动化脚本；本阶段只输出待人工审核草稿。

## 10. 风险点与影响面

| 风险点 | 影响面 | 建议处理 |
|---|---|---|
| PRD 规则未完全结构化 | 用例优先级和覆盖边界可能偏差 | 需求评审中确认业务开关、状态和异常口径 |
| 权限和数据归属不清 | 越权访问、误操作或信息泄露 | 补充角色矩阵和可见/可编辑规则 |
| 并发与幂等未定义 | 重复扣减、重复发放、重复通知或状态错乱 | 设计防重键、唯一约束和并发用例 |
| 依赖系统失败 | 订单、支付、库存、优惠、消息等链路不一致 | 明确重试、补偿和人工处理口径 |
| 老数据兼容不足 | 历史状态无法展示或无法继续流转 | 增加兼容策略和回归用例 |
{_image_risk_row(context)}

## 11. 待确认问题

{pending}

## 12. 需求到测试覆盖映射

| 需求/规则 | 测试覆盖建议 | 优先级 |
|---|---|---|
{_render_mapping_rows(context)}

## 来源文件

{source_lines}
"""


def _upsert_artifact(
    state: QAWorkflowState,
    *,
    name: str,
    artifact_type: str,
    output_path: str,
    wrote_file: bool = False,
) -> None:
    artifact = {
        "name": name,
        "artifact_type": artifact_type,
        "output_path": output_path,
        "status": "needs_human_review",
        "wrote_file": wrote_file,
    }
    state.artifacts = [
        existing for existing in state.artifacts if existing.get("name") != name
    ]
    state.artifacts.append(artifact)


def _append_llm_error(state: QAWorkflowState, message: str) -> None:
    errors = list(state.llm.get("errors", []))
    errors.append(message)
    state.llm["errors"] = errors


def _generate_with_optional_llm(
    state: QAWorkflowState,
    *,
    prompt: str,
    fallback: str,
) -> str:
    config = OpenAICompatibleConfig.from_metadata(state.llm)
    state.llm["enabled"] = state.use_llm
    state.llm["provider"] = "openai_compatible"
    state.llm["credential_env"] = config.api_key_env
    state.llm["base_url"] = config.base_url
    state.llm["model"] = config.model
    state.llm["max_input_chars"] = config.max_input_chars

    if not state.use_llm:
        return fallback

    if not config.has_api_key:
        message = (
            f"已请求 LLM，但未设置 {config.api_key_env} 环境变量，已降级为 Skeleton 生成。"
        )
        state.warnings.append(message)
        _append_llm_error(state, message)
        return fallback

    calls = int(state.llm.get("calls", 0) or 0)
    if calls >= state.max_llm_calls:
        message = "LLM 调用次数已达到本次 run 上限，已降级为 Skeleton 生成。"
        state.warnings.append(message)
        _append_llm_error(state, message)
        return fallback

    state.llm["calls"] = calls + 1
    try:
        content = OpenAICompatibleAdapter(config).generate_text(prompt)
    except Exception as exc:  # noqa: BLE001 - external SDK failures must degrade.
        message = f"LLM 调用失败，已降级为 Skeleton 生成: {exc}"
        state.warnings.append(message)
        _append_llm_error(state, message)
        return fallback

    state.llm["used"] = True
    return content


def render_requirement_analysis_skeleton(state: QAWorkflowState) -> str:
    context = _build_requirement_context(state)
    source_lines = _render_source_files(state)
    if _is_login_context(context):
        return _render_login_analysis(context, source_lines)
    return _render_generic_analysis(context, source_lines)


def _case_row(
    title: str,
    priority: str,
    precondition: str,
    steps: list[str],
    expected: str,
) -> str:
    joined_steps = "<br>".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    test_type = _infer_test_type(title)
    test_data = _infer_test_data(title, precondition)
    assertions = _infer_assertions(expected)
    pending = "无；如接口字段、错误码或页面文案未提供，则需人工补充"
    return (
        f"| AUTO_ID | PRD/需求分析 | {title} | {test_type} | {priority} | {precondition} | "
        f"{test_data} | {joined_steps} | {expected} | {assertions} | {pending} |"
    )


def _infer_test_type(title: str) -> str:
    if any(keyword in title for keyword in ("边界", "第 4", "第 5", "最大", "最小")):
        return "边界值"
    if any(keyword in title for keyword in ("异常", "错误", "失败", "超时", "弱网", "依赖")):
        return "异常"
    if any(keyword in title for keyword in ("权限", "未授权", "未登录", "token", "Authorization")):
        return "权限/认证"
    if any(keyword in title for keyword in ("重复", "幂等", "并发", "防重")):
        return "幂等/并发"
    if any(keyword in title for keyword in ("历史", "兼容")):
        return "兼容"
    if any(keyword in title for keyword in ("日志", "审计", "消息", "通知")):
        return "审计/消息"
    if any(keyword in title for keyword in ("回归", "影响")):
        return "回归"
    return "正常/规则"


def _infer_test_data(title: str, precondition: str) -> str:
    if any(keyword in title for keyword in ("边界", "最大", "最小")):
        return "按 PRD 边界准备 N-1/N/N+1、最小/最大及越界数据"
    if any(keyword in title for keyword in ("权限", "未授权", "未登录")):
        return "准备匿名用户、无权限用户、非数据归属用户和有权限用户"
    if any(keyword in title for keyword in ("重复", "幂等")):
        return "准备同一业务请求参数、幂等键或可重复点击操作"
    if "并发" in title:
        return "准备同一业务对象和多线程/多请求并发数据"
    return precondition


def _infer_assertions(expected: str) -> str:
    return f"页面展示、接口响应、数据库状态、日志/消息均需可验证；核心预期：{expected}"


RICH_TESTCASE_HEADER = [
    "用例ID",
    "需求/规则来源",
    "标题",
    "测试类型",
    "优先级",
    "前置条件",
    "测试数据",
    "测试步骤",
    "预期结果",
    "断言/证据",
    "待确认项",
]


def _is_vague_test_data(value: str) -> bool:
    return value.strip() in {"", "无", "N/A", "-", "不适用", "待确认"}


def _normalize_rich_test_type(value: str, title: str) -> str:
    allowed_types = {
        "正常/规则",
        "异常",
        "边界值",
        "权限/认证",
        "状态流转",
        "幂等/并发",
        "数据一致性",
        "兼容",
        "前后端一致",
        "接口异常",
        "安全/异常",
        "回归",
        "审计/消息",
        "确认/风险",
    }
    stripped = value.strip()
    if stripped in allowed_types:
        return stripped

    combined = f"{stripped} {title}"
    if any(keyword in combined for keyword in ("并发", "幂等", "防重", "重复")):
        return "幂等/并发"
    if any(keyword in combined for keyword in ("一致", "数据库", "落库", "字段")):
        return "数据一致性"
    if any(keyword in combined for keyword in ("权限", "认证", "未登录", "token", "授权")):
        return "权限/认证"
    if any(keyword in combined for keyword in ("状态", "流转", "过期", "失效")):
        return "状态流转"
    if "安全" in combined:
        return "安全/异常"
    if any(keyword in combined for keyword in ("接口", "超时", "异常", "失败")):
        return "接口异常"
    if any(keyword in combined for keyword in ("分支", "变体")):
        return "正常/规则"
    if any(keyword in combined for keyword in ("兼容", "设备", "浏览器", "历史")):
        return "兼容"
    if any(keyword in combined for keyword in ("前端", "页面", "展示")):
        return "前后端一致"
    if any(keyword in combined for keyword in ("日志", "审计", "消息", "通知")):
        return "审计/消息"
    if "回归" in combined:
        return "回归"
    if any(keyword in combined for keyword in ("边界", "必填", "格式", "为空", "不存在")):
        return "边界值"
    if any(keyword in combined for keyword in ("确认", "待确认", "风险")):
        return "确认/风险"
    return "正常/规则"


def _fill_rich_test_data(title: str, test_type: str, precondition: str) -> str:
    if "邀请" in title:
        return (
            "老用户A、邀请链接invite_code、被邀请新用户B、活动开关开启；"
            "需校验邀请关系、有效邀请状态和奖励发放记录"
        )
    if "头像框" in title:
        return "已完成测试用户A、头像框ID=crispy-worker、发放时间T0、有效期15天"
    if "未登录" in title or "游客" in title:
        return "匿名用户会话、未携带登录态/token、活动H5入口URL、微信/浏览器访问环境"
    if "退出" in title or "无操作" in title:
        return "已登录用户A、活动页已加载、未选择任何题目、本地缓存和服务端暂存状态"
    if "防刷" in title or "大量" in title:
        return "同一账号/设备/IP在短时间内连续触发多次请求，准备阈值内和阈值外数据"
    if "图片" in title or "诊断书" in title:
        return "轻度/中度/重度诊断书各一份、图片资源URL、平台logo和素材资源清单"
    if "兼容" in test_type or "设备" in title:
        return "iOS Safari、Android Chrome、微信内置浏览器、不同屏幕宽度和网络环境"
    if "回归" in test_type:
        return "上一版基线数据、核心P0链路、历史邀请/奖励/话题区数据各一组"
    return precondition or "按前置条件准备账号、角色、状态、开关和业务数据"


def _enrich_rich_testcase_table(markdown: str) -> str:
    lines = markdown.splitlines()
    header_seen = False
    enriched: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("| 用例ID |"):
            header_seen = True
            enriched.append(line)
            continue
        if not header_seen or not stripped.startswith("|") or not stripped.endswith("|"):
            enriched.append(line)
            continue

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if set("".join(cells)) <= {"-", ":"}:
            enriched.append(line)
            continue
        if len(cells) != len(RICH_TESTCASE_HEADER):
            # Drop malformed table rows. The quality gate still enforces the minimum valid row count.
            continue
        if cells == RICH_TESTCASE_HEADER:
            enriched.append(line)
            continue
        cells[3] = _normalize_rich_test_type(cells[3], cells[2])
        if _is_vague_test_data(cells[6]):
            cells[6] = _fill_rich_test_data(cells[2], cells[3], cells[5])
            enriched.append("| " + " | ".join(cells) + " |")
            continue
        enriched.append(line)
    return "\n".join(enriched) + ("\n" if markdown.endswith("\n") else "")


def _login_testcase_rows() -> list[str]:
    return [
        _case_row(
            "手机号密码登录成功返回 Bearer token",
            "P0",
            "存在正常用户账号，账号未锁定，手机号和密码正确，登录开关开启",
            ["调用 `POST /api/v1/auth/login`", "提交合法手机号和正确密码"],
            "接口返回成功；响应包含 `access_token`、`token_type=Bearer`、`expires_in`；不返回密码字段",
        ),
        _case_row(
            "登录成功后携带 token 访问受保护资源",
            "P0",
            "已获得未过期 Bearer token，用户有访问 `/api/v1/profile` 权限",
            ["在请求头加入 `Authorization: Bearer <token>`", "访问 `GET /api/v1/profile`"],
            "受保护资源访问成功；接口识别当前用户；无重新登录提示",
        ),
        _case_row(
            "手机号为空时拒绝登录",
            "P1",
            "登录入口可访问，账号数据不限",
            ["手机号留空", "输入任意密码并提交登录"],
            "前端或接口阻断提交；返回手机号必填或 `INVALID_PHONE`；不生成 token",
        ),
        _case_row(
            "手机号格式不符合大陆手机号规则时拒绝登录",
            "P1",
            "登录入口可访问",
            ["输入 `12345` 或非数字手机号", "输入任意密码并提交登录"],
            "接口返回 400/`INVALID_PHONE` 或等价错误；错误文案为手机号格式不正确",
        ),
        _case_row(
            "密码为空时拒绝登录",
            "P1",
            "存在正常用户账号，账号未锁定",
            ["输入合法手机号", "密码留空并提交登录"],
            "请求被阻断或返回密码必填错误；不累计为密码错误次数的规则待确认",
        ),
        _case_row(
            "密码错误但未达到锁定阈值时返回安全文案",
            "P0",
            "存在正常用户账号，连续错误次数为 0 至 3",
            ["输入合法手机号", "输入错误密码提交登录"],
            "接口返回 401/`INVALID_CREDENTIALS`；文案为“手机号或密码错误”；不泄露账号是否存在",
        ),
        _case_row(
            "不存在手机号与错误密码返回一致安全文案",
            "P1",
            "准备一个不存在的手机号和一个存在账号的错误密码场景",
            ["分别提交不存在手机号和存在手机号错误密码", "比较响应状态码、业务码和 message"],
            "两个场景的错误文案不暴露账号存在性；响应不包含敏感账号状态",
        ),
        _case_row(
            "连续第 4 次密码错误仍不锁定账号",
            "P0",
            "同一锁定计数维度已连续输错 3 次，账号未锁定",
            ["再次输入错误密码", "提交登录并查询响应"],
            "返回密码错误；账号仍未进入锁定状态；错误计数变为 4",
        ),
        _case_row(
            "连续第 5 次密码错误触发 15 分钟锁定",
            "P0",
            "同一锁定计数维度已连续输错 4 次，账号未锁定",
            ["再次输入错误密码", "提交登录并检查账号状态"],
            "接口返回账号锁定或密码错误后进入锁定；锁定到期时间约为当前时间加 15 分钟",
        ),
        _case_row(
            "账号锁定期间使用正确密码仍被拒绝",
            "P0",
            "账号处于 15 分钟锁定期内，用户输入正确密码",
            ["提交登录请求", "检查响应和账号状态"],
            "接口返回 423/`ACCOUNT_LOCKED`；不签发 token；账号保持锁定状态",
        ),
        _case_row(
            "锁定期间返回剩余锁定时间口径",
            "P1",
            "账号处于锁定期内，剩余锁定时间大于 0",
            ["提交登录请求", "检查响应体、页面提示和日志"],
            "提示账号暂时锁定；如产品要求返回剩余时间，字段名、单位和展示一致",
        ),
        _case_row(
            "锁定期结束后允许重新登录",
            "P1",
            "账号锁定已超过 15 分钟，用户密码正确",
            ["等待或调整测试数据到锁定过期", "提交正确手机号和密码"],
            "登录成功并返回 token；锁定状态解除；错误计数清理策略符合确认结论",
        ),
        _case_row(
            "token 过期后访问受保护资源提示重新登录",
            "P0",
            "持有已过期 Bearer token",
            ["使用过期 token 访问 `GET /api/v1/profile`", "检查接口响应和客户端提示"],
            "接口返回 `TOKEN_EXPIRED`；message 为登录已过期请重新登录；受保护数据不返回",
        ),
        _case_row(
            "未携带 Authorization 访问受保护资源被拒绝",
            "P1",
            "用户未登录或请求头不包含 Authorization",
            ["直接访问 `GET /api/v1/profile`", "检查响应码、业务码和页面跳转"],
            "访问被拒绝；提示登录或重新登录；不返回用户资料",
        ),
        _case_row(
            "Authorization 格式错误时拒绝访问",
            "P1",
            "准备格式错误的 token，例如缺少 Bearer 前缀或 token 被截断",
            ["携带错误 Authorization 请求受保护资源", "检查响应"],
            "接口拒绝访问；错误码和文案与认证失败规则一致；服务端不抛出 500",
        ),
        _case_row(
            "重复点击登录按钮不产生多次异常状态变更",
            "P1",
            "账号未锁定，前端存在快速重复提交可能",
            ["快速连续提交两次相同登录请求", "检查响应、错误计数和登录日志"],
            "成功场景不生成异常重复状态；失败场景错误计数按确认的幂等/防重策略处理",
        ),
        _case_row(
            "并发错误密码请求下锁定计数保持一致",
            "P1",
            "同一账号接近锁定阈值，准备并发错误密码请求",
            ["并发提交多次错误密码", "查询账号锁定状态和错误计数"],
            "不会绕过 5 次锁定，也不会出现负数、重复锁定或状态回退",
        ),
        _case_row(
            "登录接口超时或认证依赖失败时不落脏状态",
            "P2",
            "模拟认证服务、账号服务或网络超时",
            ["提交登录请求", "观察接口响应、错误计数和日志"],
            "返回可识别失败提示；不签发 token；错误计数和锁定状态按确认策略处理",
        ),
        _case_row(
            "历史账号错误计数和锁定字段兼容",
            "P2",
            "准备缺少新锁定字段或旧状态枚举的历史账号数据",
            ["使用历史账号登录", "检查登录结果、状态展示和日志"],
            "接口不报 500；旧数据可兼容处理；必要字段按迁移或默认策略生效",
        ),
        _case_row(
            "登录失败、锁定和 token 过期日志可审计",
            "P2",
            "日志/审计采集开关按测试环境配置开启",
            ["分别触发密码错误、账号锁定、token 过期", "检查日志或审计记录"],
            "关键事件包含账号标识脱敏、时间、结果和错误码；不记录明文密码或 token",
        ),
    ]


def _generic_testcase_rows(context: RequirementContext) -> list[str]:
    subject = context.title
    primary_rule = _first_non_empty(context.scope_items, f"{subject} 主业务规则")
    endpoint = context.endpoints[0] if context.endpoints else "目标业务接口"
    field_desc = ", ".join(context.fields[:5]) if context.fields else "PRD/API 定义的核心字段"
    return [
        _case_row(
            f"{subject} 主流程成功处理",
            "P0",
            "业务用户账号有效，具备操作权限；必要业务开关开启；测试数据处于可操作初始状态",
            ["进入功能入口或调用目标接口", f"按 PRD 填写 {field_desc}", "提交业务操作"],
            "页面/接口返回成功；业务记录状态更新正确；关键字段落库或返回值与 PRD 一致",
        ),
        _case_row(
            f"{subject} 核心规则校验符合 PRD",
            "P0",
            "准备满足前置状态的数据；规则来源为 PRD 功能范围或验收标准",
            [f"围绕规则“{primary_rule}”提交操作", "检查接口响应、页面展示和状态"],
            "系统按规则处理；无绕过校验；结果可追溯到 PRD 或接口文档",
        ),
        _case_row(
            f"{subject} 未授权用户不能操作",
            "P0",
            "使用未登录账号、无权限账号或非数据归属账号",
            ["访问功能入口或调用接口", "尝试提交或查看目标数据"],
            "系统拒绝访问或操作；不返回敏感数据；必要时记录权限审计",
        ),
        _case_row(
            f"{subject} 必填字段缺失时阻断提交",
            "P1",
            f"业务用户有权限；准备缺失 {field_desc} 中任一必填项的数据",
            ["清空一个必填字段", "提交业务操作"],
            "前端或接口返回明确必填错误；不创建或更新业务记录",
        ),
        _case_row(
            f"{subject} 字段格式错误时返回可识别错误",
            "P1",
            "业务用户有权限；准备格式非法的手机号、金额、数量、时间或枚举值",
            ["填写格式错误数据", "提交业务操作"],
            "接口返回参数错误；页面提示与接口错误一致；不产生脏数据",
        ),
        _case_row(
            f"{subject} 边界值按最小和最大限制处理",
            "P1",
            "已确认金额、数量、次数、时间或文本长度边界",
            ["分别提交边界内、边界值、边界外数据", "检查响应和落库"],
            "边界内和边界值按需求成功或失败；边界外被拒绝且提示明确",
        ),
        _case_row(
            f"{subject} 状态不允许时阻断流转",
            "P0",
            "准备已取消、已失效、已完成或不可编辑状态的数据",
            ["对该数据再次执行目标操作", "检查状态和返回结果"],
            "操作被拒绝；原状态不变；错误码和页面提示一致",
        ),
        _case_row(
            f"{subject} 重复提交保持幂等",
            "P1",
            "业务用户有权限；准备可提交数据；前端存在重复点击或接口重放可能",
            ["连续两次提交相同请求", "检查数据库、消息和日志"],
            "不会重复创建、扣减、发放、结算或通知；返回结果符合幂等策略",
        ),
        _case_row(
            f"{subject} 并发操作保持数据一致",
            "P1",
            "准备同一业务数据和两个并发请求或两个角色同时操作",
            ["并发提交目标操作", "检查最终状态、库存/金额/次数和日志"],
            "只有符合规则的请求成功；最终状态唯一且数据无超扣、超发或状态回退",
        ),
        _case_row(
            f"{subject} 上游依赖失败时可恢复",
            "P2",
            "模拟商品、订单、支付、库存、优惠、会员、消息或结算依赖失败",
            ["提交业务操作", "观察接口响应、状态和补偿记录"],
            "系统返回可识别失败；本地状态不脏写；重试或人工处理口径明确",
        ),
        _case_row(
            f"{subject} 接口超时或弱网下提示一致",
            "P2",
            f"目标接口为 `{endpoint}` 或 PRD 对应接口；网络延迟或超时可模拟",
            ["在弱网或超时条件下提交操作", "刷新页面或重试查询"],
            "用户看到明确状态；服务端无重复处理；重试后状态与接口结果一致",
        ),
        _case_row(
            f"{subject} 前后端展示与接口状态一致",
            "P1",
            "准备成功、失败、处理中和终态数据各一条",
            ["分别通过页面和接口查询数据", "比对状态、文案、金额/数量/时间字段"],
            "页面展示、接口返回和数据库状态一致；无过期状态或错误按钮",
        ),
        _case_row(
            f"{subject} 历史数据兼容展示和操作",
            "P2",
            "准备旧版本字段缺失或历史状态枚举的数据",
            ["打开详情页或调用查询接口", "尝试允许的后续操作"],
            "历史数据可正常展示；不因缺失字段报错；不可操作项被正确禁用",
        ),
        _case_row(
            f"{subject} 消息通知或日志按需求记录",
            "P2",
            "消息、通知、埋点或审计开关按测试环境配置开启",
            ["触发主流程成功和失败场景", "检查消息、通知、埋点或审计日志"],
            "如需求涉及则记录完整；如需求未说明则形成待确认项，不记录敏感明文",
        ),
        _case_row(
            f"{subject} 回归影响范围验证",
            "P1",
            "准备与本需求共享账号、订单、商品、支付、库存、优惠或会员数据的已有功能",
            ["执行目标需求主流程", "回归检查关联查询、列表、详情和下游处理"],
            "关联功能不受异常影响；共享字段、状态和消息保持一致",
        ),
    ]


def _image_testcase_rows(context: RequirementContext) -> list[str]:
    if not context.requirement_has_images:
        return []
    return [
        _case_row(
            "图片内容未分析的人工确认项已记录",
            "P2",
            "input/requirement.md 包含图片/原型图引用",
            [
                "查看需求正文中的图片引用位置",
                "人工确认图片中是否存在未写入正文的字段、按钮、状态、弹窗、权限差异或交互规则",
            ],
            "测试用例不把图片内容当成已知事实；未写入正文的信息记录为待确认或待补充",
        ),
    ]


def render_testcase_skeleton(state: QAWorkflowState) -> str:
    context = _build_requirement_context(state)
    source_lines = _render_source_files(state)
    analysis_source = (
        "本次运行生成的需求分析草稿"
        if state.draft_artifacts.get("requirement_analysis")
        else "PRD 工作区现有材料"
    )
    rows = _login_testcase_rows() if _is_login_context(context) else _generic_testcase_rows(context)
    rows = [*rows, *_image_testcase_rows(context)]
    numbered_rows = [
        row.replace("| AUTO_ID |", f"| TC-{index:03d} |", 1)
        for index, row in enumerate(rows, start=1)
    ]
    known_gaps = [
        *(
            context.pending_items
            or [
                "PRD 未明确全部字段边界、角色矩阵、状态枚举、幂等策略和依赖失败处理口径。",
                "接口错误码、页面文案、日志/审计字段和历史数据兼容策略需人工确认。",
            ]
        ),
        *_image_pending_questions(context),
    ]
    return f"""---
status: needs_human_review
artifact_type: testcase_draft
human_review_required: true
generated_by: Runtime MVP Review Grade Draft
---

# 测试用例草稿

> 状态：needs_human_review
> 分析依据：{analysis_source}
> 注意：当前内容为可审核草稿，不代表正式 QA 结论。

| 用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | 测试步骤 | 预期结果 | 断言/证据 | 待确认项 |
|---|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(numbered_rows)}

## 覆盖矩阵

| 覆盖维度 | 覆盖说明 | 优先级 |
|---|---|---|
| 主流程 | 成功路径、核心响应字段、状态更新 | P0 |
| 关键分支 | 权限、角色、状态、锁定/审核/取消/失效等分支 | P0/P1 |
| 校验与边界 | 必填、格式、金额/数量/时间/次数/文本边界 | P1 |
| 异常与依赖 | 接口异常、弱网、超时、上游依赖失败 | P1/P2 |
| 一致性与回归 | 数据一致性、前后端一致、历史数据、日志/消息/审计 | P1/P2 |

## 待确认问题

{_format_bullets(known_gaps, "待确认：PRD 未列出待确认项。")}

## 来源文件

{source_lines}

## 待人工确认

- [ ] 测试用例是否覆盖主流程、异常流程和边界条件。
- [ ] 前置条件、测试数据和预期结果是否准确。
- [ ] 是否允许后续生成 API/UI 自动化脚本草稿。
"""


def requirement_analysis_generation_node(state: QAWorkflowState) -> QAWorkflowState:
    if state.task_type not in {TASK_ANALYSIS, TASK_MVP}:
        return state
    state.record_node("requirement_analysis_generation_node")
    if state.errors:
        return state

    prompt = build_requirement_analysis_prompt(
        state.loaded_files,
        prd_prefix=_prd_prefix(state),
        rag_context=_build_rag_context(state),
        max_input_chars=int(state.llm.get("max_input_chars") or 32000),
    )
    state.warnings.extend(prompt.warnings)
    artifact = _generate_with_optional_llm(
        state,
        prompt=prompt.prompt,
        fallback=render_requirement_analysis_skeleton(state),
    )
    state.draft_artifacts["requirement_analysis"] = artifact
    state.draft_artifact = artifact
    output_path = state.output_paths.get("requirement_analysis")
    if output_path:
        state.output_path = output_path if state.task_type == TASK_ANALYSIS else state.output_path
        _upsert_artifact(
            state,
            name="requirement_analysis",
            artifact_type="requirement_analysis",
            output_path=output_path,
        )
    return state


def testcase_generation_mvp_node(state: QAWorkflowState) -> QAWorkflowState:
    if state.task_type not in {TASK_TESTCASE_GENERATION, TASK_MVP}:
        return state
    state.record_node("testcase_generation_node")
    if state.errors:
        return state

    prompt = build_testcase_prompt(
        state.loaded_files,
        prd_prefix=_prd_prefix(state),
        generated_analysis=state.draft_artifacts.get("requirement_analysis"),
        rag_context=_build_rag_context(state),
        max_input_chars=int(state.llm.get("max_input_chars") or 32000),
    )
    state.warnings.extend(prompt.warnings)
    artifact = _generate_with_optional_llm(
        state,
        prompt=prompt.prompt,
        fallback=render_testcase_skeleton(state),
    )
    artifact = _enrich_rich_testcase_table(artifact)
    state.draft_artifacts["testcases"] = artifact
    state.draft_artifact = artifact
    output_path = state.output_paths.get("testcases")
    if output_path:
        if state.task_type == TASK_TESTCASE_GENERATION:
            state.output_path = output_path
        _upsert_artifact(
            state,
            name="testcases",
            artifact_type="testcase_draft",
            output_path=output_path,
        )
    return state
