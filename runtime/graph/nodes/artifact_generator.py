"""LEGACY ONLY: old langgraph_app artifact generator.

Merged for current runtime into mvp_generation nodes.
"""

from __future__ import annotations

from runtime.graph.state import QAWorkflowState

# ── 意图 → 产物类型映射 ──────────────────────────────────
INTENT_DESCRIPTIONS: dict[str, str] = {
    "requirement_analysis": "需求分析",
    "testcase_generation": "测试用例",
    "api_test_generation": "API 接口测试",
    "ui_test_generation": "UI 端到端测试",
    "test_execution": "测试执行计划",
    "failure_analysis": "失败分析",
    "bug_draft": "缺陷草稿",
    "report_generation": "QA 报告",
    "archive": "归档检查",
}

# archive 意图不需要生成
SKIP_GENERATION_INTENTS = {"archive"}


def _source_list(state: QAWorkflowState) -> str:
    """生成已加载文件的摘要列表。"""
    if not state.loaded_files:
        return "（无加载文件）"
    return "\n".join(f"- `{path}`" for path in sorted(state.loaded_files))


def _build_draft(
    state: QAWorkflowState,
    *,
    title: str,
    extra_sections: str = "",
) -> str:
    """生成统一格式的产物草稿。"""
    mode = "debug-preview-write" if state.debug_approve_preview_write else "dry-run"
    artifact_type = (state.intent or "unknown") + "_draft"
    description = INTENT_DESCRIPTIONS.get(state.intent or "", state.intent or "unknown")

    lines = [
        "---",
        "status: needs_human_review",
        "human_review_required: true",
        f"artifact_type: {artifact_type}",
        "generated_by: Runtime Skeleton",
        "---",
        "",
        f"# {title}",
        "",
        "> 状态：needs_human_review",
        f"> 来源：Runtime Skeleton {mode}",
        "> 注意：当前内容为 Runtime 最小骨架生成，不代表最终 AI 生成质量。",
        "",
        "## 意图识别",
        "",
        f"- 用户输入：`{state.user_input}`",
        f"- 识别意图：`{state.intent}`（{description}）",
        "",
        "## 来源文件",
        "",
        _source_list(state),
        "",
    ]

    if extra_sections:
        lines.append(extra_sections)

    lines.append("")
    lines.append("## 待人工确认")
    lines.append("")
    lines.append("- [ ] 输出内容是否准确。")
    lines.append("- [ ] 是否需要进一步精炼或补充。")
    lines.append("- [ ] 是否允许继续执行后续步骤。")
    lines.append("")

    return "\n".join(lines)


def _testcase_table_skeleton() -> str:
    """生成测试用例表格骨架。"""
    return "\n".join(
        [
            "| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |",
            "|---|---|---|---|---|",
            "| 待补充：基于需求主流程生成 | P0 | 待人工确认 | "
            "待接入 LangChain 后生成 | 待人工确认 |",
        ]
    )


def _build_analysis_sections(state: QAWorkflowState) -> str:
    requirement_content = (
        state.loaded_files.get(
            next((k for k in state.loaded_files if k.endswith("input/requirement.md")), "")
        )
        or ""
    )
    if len(requirement_content) > 200:
        requirement_summary = requirement_content[:200] + "..."
    elif requirement_content:
        requirement_summary = requirement_content
    else:
        requirement_summary = "（未加载需求文档）"
    return (
        "## 需求摘要\n\n"
        f"{requirement_summary}\n\n"
        "## 分析要点\n\n"
        "- 待补充：基于需求进行功能范围分析\n"
        "- 待补充：识别业务规则和约束\n"
        "- 待补充：提取验收标准\n"
    )


def _build_testcase_sections(state: QAWorkflowState) -> str:
    """解析需求文档中的功能点，生成有针对性的测试用例。"""
    # ── 从 loaded_files 中提取 input/requirement.md 内容 ──
    req_content = ""
    for path in sorted(state.loaded_files.keys()):
        if "input/requirement.md" in path:
            content = state.loaded_files.get(path, "")
            if isinstance(content, str) and len(content) > len(req_content):
                req_content = content

    if not req_content:
        return "## 测试用例\n\n" + _testcase_table_skeleton() + "\n"

    # ── 按标题行拆分需求段落 ──
    import re

    sections = re.split(r"(?=^#{1,3}\s)", req_content, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    # ── 关键词 → 测试用例生成规则 ──
    feature_rules = [
        (
            r"启动页|开屏|splash|闪屏",
            "启动页/开屏广告",
            [
                (
                    "冷启动时展示开屏广告",
                    "P0",
                    "APP 已安装，首次冷启动",
                    "1. 杀死 APP 进程\n2. 点击 APP 图标启动\n3. 观察开屏广告展示",
                    "开屏广告正常展示，倒计时 3s 后自动进入首页",
                ),
                (
                    "热启动不展示开屏广告",
                    "P0",
                    "APP 已在后台运行",
                    "1. APP 在前台\n2. 按 Home 键退到后台\n3. 重新点击 APP 图标唤醒",
                    "不展示开屏广告，直接进入首页",
                ),
                (
                    "点击跳过按钮直接进入首页",
                    "P0",
                    "开屏广告展示中",
                    "1. 冷启动 APP\n2. 在广告展示期间点击「跳过」按钮",
                    "跳过广告，直接进入 APP 首页",
                ),
                (
                    "点击广告区域跳转至落地页",
                    "P0",
                    "开屏广告展示中",
                    "1. 冷启动 APP\n2. 点击广告区域（非跳过按钮）",
                    "跳转至广告落地页（帖子详情 / H5）",
                ),
                (
                    "落地页返回直接进首页，不再展示开屏",
                    "P1",
                    "已从落地页返回",
                    "1. 点击开屏广告进入落地页\n2. 从落地页返回",
                    "直接进入 APP 首页，不重复展示开屏广告",
                ),
                (
                    "每日仅展示一次开屏广告",
                    "P1",
                    "当日已展示过开屏",
                    "1. 首次冷启动展示开屏\n2. 退出 APP 后再次冷启动",
                    "第二次冷启动不再展示开屏广告",
                ),
                (
                    "开屏素材可配置图片或视频",
                    "P1",
                    "后台配置素材",
                    "1. 后台配置图片素材\n2. 冷启动查看\n3. 切换为视频素材\n4. 冷启动查看",
                    "图片和视频素材均正常展示",
                ),
                (
                    "倒计时 3s 结束自动进入首页",
                    "P0",
                    "开屏广告展示中",
                    "1. 冷启动 APP\n2. 等待倒计时 3s 结束",
                    "倒计时结束后自动进入 APP 首页",
                ),
            ],
        ),
        (
            r"消息|通知|小铃铛|角标",
            "消息中心/活动通知",
            [
                (
                    "消息中心按时间倒序展示活动",
                    "P1",
                    "有多个活动通知",
                    "1. 触发多个活动通知\n2. 打开消息中心的活动板块",
                    "活动列表按时间倒序排列",
                ),
                (
                    "未读活动展示小红点",
                    "P1",
                    "有未查看的活动",
                    "1. 触发新活动通知\n2. 观察小铃铛图标",
                    "小铃铛上展示小红点/数字角标",
                ),
                (
                    "当日首次进入有未读活动时展开提示",
                    "P1",
                    "当日首次启动",
                    "1. 当日首次打开 APP\n2. 有未查看活动",
                    "展开提示引导用户参与活动",
                ),
            ],
        ),
        (
            r"官号|官方认证|认证标识|V字|排序强插|强插|官号认证",
            "官号认证与排序强插",
            [
                (
                    "官方号展示 V 字认证标识",
                    "P0",
                    "已认证的官方号",
                    "1. 访问 feed 页\n2. 查看官方号的头像展示位置",
                    "官方号头像旁展示 V 字认证标识",
                ),
                (
                    "点击 V 字标识展示认证浮层",
                    "P1",
                    "官方号 V 字展示中",
                    "1. 点击 V 字认证标识",
                    "弹出浮层提示「交子立方官方认证账号」",
                ),
                (
                    "V 标识在各头像位均展示",
                    "P1",
                    "官方号在多个页面出现",
                    "1. 查看 feed 页\n2. 查看客态个人页\n3. 查看我的页\n4. 查看去玩活动页",
                    "所有头像展示位置均显示 V 字标识",
                ),
                (
                    "官方号内容强插信息流前两位",
                    "P0",
                    "官方号发布内容",
                    "1. 官方号发布指定内容\n2. 刷新 feed 页",
                    "指定内容出现在信息流前两位（非置顶）",
                ),
                (
                    "24 小时内同一内容仅强插一次",
                    "P1",
                    "内容已强插",
                    "1. 官方号发布内容后首次强插\n2. 再次刷新 feed 页（24h 内）",
                    "同一内容不再重复强插",
                ),
                (
                    "单日仅强插一条内容",
                    "P0",
                    "官方号发布多条内容",
                    "1. 官方号在同一天发布多条内容\n2. 依次刷新 feed 页",
                    "单日最多有一条内容被强插",
                ),
            ],
        ),
        (
            r"丑东西|丑东西大赛|丑东西排行|丑东西广场",
            "丑东西大赛活动",
            [
                (
                    "活动 H5 页包含所有模块",
                    "P0",
                    "活动进行中",
                    "1. 打开丑东西大赛 H5 页面",
                    "页面包含：头图、活动时间、活动简介、排行榜、广场、活动奖励、参与入口",
                ),
                (
                    "活动广场聚合符合规则帖子",
                    "P1",
                    "有帖子参与活动",
                    "1. 用户发布带活动标签的帖子\n2. 打开活动广场",
                    "所有符合活动规则的帖子聚合展示在广场",
                ),
                (
                    "点赞触发「丑东西」特效",
                    "P0",
                    "符合条件的帖子",
                    "1. 打开符合条件的帖子\n2. 点击点赞按钮",
                    "点赞后触发「丑东西」疯狂特效动画",
                ),
                (
                    "话题页新增热度排序",
                    "P1",
                    "话题页有多个帖子",
                    "1. 进入话题详情页\n2. 切换到热度排序",
                    "帖子按热度（点赞/评论等）从高到低排序",
                ),
                (
                    "发帖和评论区可发布短链",
                    "P1",
                    "发帖/评论时",
                    "1. 发帖时输入短链\n2. 评论区输入短链",
                    "短链可点击，跳转到 H5 活动详情页",
                ),
                (
                    "丑东西大赛新增头像框奖励",
                    "P1",
                    "用户获得奖励",
                    "1. 用户满足获奖条件\n2. 查看头像框奖励",
                    "头像框可配置佩戴时长和样式，用户可佩戴",
                ),
            ],
        ),
        (
            r"浴室歌王|浴室歌王争霸赛",
            "浴室歌王争霸赛活动",
            [
                (
                    "浴室歌王争霸赛 H5 页面功能正常",
                    "P0",
                    "活动进行中",
                    "1. 打开浴室歌王争霸赛 H5 活动页",
                    "页面正常加载，包含所有必要模块",
                ),
                (
                    "用户可参与浴室歌王活动",
                    "P0",
                    "活动期内",
                    "1. 进入活动页\n2. 点击参与入口\n3. 完成参与流程",
                    "用户成功参与活动，内容正确展示",
                ),
            ],
        ),
        (
            r"资源位|运营位|后台配置|通用资源位",
            "通用运营位/资源位",
            [
                (
                    "后台可配置资源位素材",
                    "P1",
                    "运营后台",
                    "1. 进入资源位配置后台\n2. 选择生效时间段\n3. 配置活动素材",
                    "配置成功，一个生效时间段仅支持一个活动",
                ),
                (
                    "素材配置支持图片和视频",
                    "P1",
                    "运营后台",
                    "1. 选择图片素材上传\n2. 选择视频素材上传",
                    "两种素材格式均支持配置",
                ),
            ],
        ),
    ]

    output_sections = []
    for pattern, feature_name, cases in feature_rules:
        if re.search(pattern, req_content, re.IGNORECASE):
            rows = "\n".join(
                f"| {title} | {pri} | {precond} | {steps} | {expected} |"
                for title, pri, precond, steps, expected in cases
            )
            output_sections.append(
                f"### {feature_name}\n\n"
                f"| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |\n"
                f"|---|---|---|---|---|\n{rows}\n"
            )

    if not output_sections:
        return "## 测试用例\n\n" + _testcase_table_skeleton() + "\n"

    return "## 测试用例\n\n" + "\n".join(output_sections)


def _build_api_test_sections(state: QAWorkflowState) -> str:
    return (
        "## API 接口测试\n\n"
        "| 接口 | 方法 | 参数 | 预期状态码 | 预期响应 |\n"
        "|---|---|---|---|---|\n"
        "| 待补充 | GET/POST/PUT/DELETE | 待补充 | 200/4xx/5xx | 待补充 |\n"
    )


def _build_ui_test_sections(state: QAWorkflowState) -> str:
    return (
        "## UI 测试场景\n\n"
        "| 页面 | 操作 | 预期结果 |\n"
        "|---|---|---|\n"
        "| 待补充 | 点击/输入/导航 | 待补充 |\n"
    )


def _build_test_execution_sections() -> str:
    return (
        "## 测试执行计划\n\n" "- 执行范围：待确认\n" "- 测试环境：待确认\n" "- 回归策略：待确认\n"
    )


def _build_failure_analysis_sections() -> str:
    return (
        "## 失败分析\n\n"
        "| 失败类型 | 失败描述 | 根因分析 | 修复建议 |\n"
        "|---|---|---|---|\n"
        "| 待分类 | 待补充 | 待分析 | 待补充 |\n"
    )


def _build_bug_draft_sections() -> str:
    return (
        "## 缺陷草稿\n\n"
        "- **标题**：待补充\n"
        "- **严重等级**：P0/P1/P2/P3\n"
        "- **复现步骤**：待补充\n"
        "- **实际结果**：待补充\n"
        "- **预期结果**：待补充\n"
        "- **附件**：待补充\n"
    )


def _build_report_sections() -> str:
    return (
        "## QA 报告\n\n"
        "### 测试概要\n\n"
        "- 总用例数：待补充\n"
        "- 通过：待补充\n"
        "- 失败：待补充\n"
        "- 阻塞：待补充\n\n"
        "### 风险结论\n\n"
        "待补充\n\n"
        "### 建议\n\n"
        "待补充\n"
    )


def _build_archive_sections() -> str:
    return (
        "## 归档检查清单\n\n"
        "- [ ] 所有测试用例已执行完毕\n"
        "- [ ] 所有缺陷已关闭或评估\n"
        "- [ ] QA 报告已生成\n"
        "- [ ] 验收标准已满足\n"
    )


# ── 意图 → 构建函数映射 ──────────────────────────────────
_INTENT_BUILDERS: dict[str, tuple[str, str]] = {
    "requirement_analysis": ("需求分析文档", _build_analysis_sections),
    "testcase_generation": ("测试用例草稿", _build_testcase_sections),
    "api_test_generation": ("API 接口测试草稿", _build_api_test_sections),
    "ui_test_generation": ("UI 测试草稿", _build_ui_test_sections),
    "test_execution": ("测试执行计划", _build_test_execution_sections),
    "failure_analysis": ("失败分析草稿", _build_failure_analysis_sections),
    "bug_draft": ("缺陷草稿", _build_bug_draft_sections),
    "report_generation": ("QA 报告草稿", _build_report_sections),
    "archive": ("归档检查单", _build_archive_sections),
}


def artifact_generation_node(state: QAWorkflowState) -> QAWorkflowState:
    """统一的产物生成节点，根据 state.intent 分发到不同构建器。"""
    state.record_node("artifact_generation_node")
    if state.errors:
        return state

    if state.intent in SKIP_GENERATION_INTENTS:
        # archive 等不需要生成产物
        return state

    title_builder = _INTENT_BUILDERS.get(state.intent)
    if title_builder is None:
        state.errors.append(f"未知意图「{state.intent}」，无法生成产物。")
        return state

    title, section_fn = title_builder
    extra = section_fn(state) if callable(section_fn) else str(section_fn)
    state.draft_artifact = _build_draft(state, title=title, extra_sections=extra)

    return state
