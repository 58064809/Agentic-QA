# 任务 014：补齐评审级质量门与 MarkItDown 实现

## 任务目标

审核发现 012B 和 013 当前只看到任务文件，master 上没有实际代码落地。本任务要求补齐真实实现。

## 必须修复的问题

1. `runtime/graph/nodes/mvp_quality.py` 仍然只检查基础章节和表头，必须升级为评审级质量门。
2. `runtime/llm/prompt_builder.py` 仍然只要求基础章节，必须升级为领导评审级 Prompt。
3. `pyproject.toml` 未加入 MarkItDown 依赖。
4. `runtime/tools/document_converter.py` 不存在。
5. `runtime/graph/nodes/requirement_normalizer.py` 不存在。
6. analyze、mvp、generate-testcases 流程尚未接入需求文档归一化节点。
7. 当前文本链路不能分析原型图内容，必须补充边界说明和后续方案。

## 评审级质量门要求

需求分析必须检查 12 个章节：

- 需求背景与目标
- 业务范围
- 角色与权限
- 主流程拆解
- 分支流程与异常流程
- 业务规则清单
- 数据字段与状态流转
- 接口与依赖系统
- 测试范围建议
- 风险点与影响面
- 待确认问题
- 需求到测试覆盖映射

测试用例必须检查：

- 固定列：标题、优先级、前置条件、测试步骤、预期结果
- 不允许“用例类型”列
- 至少 15 条非表头用例
- 至少 1 条 P0
- 优先级只能是 P0/P1/P2/P3
- Skeleton 占位内容不能通过
- 至少覆盖主流程、异常、边界、权限、状态、幂等、数据一致性、兼容、回归、接口、消息、日志、审计中的 4 类

## MarkItDown 要求

1. 在 `pyproject.toml` 加入 MarkItDown 依赖，以本地可安装为准。
2. 新增 `runtime/tools/document_converter.py`。
3. 新增 `runtime/graph/nodes/requirement_normalizer.py`。
4. 支持目标 PRD 工作区内的 `requirement.md`、`requirement.docx`、`requirement.pdf`、`requirement.txt`、`requirement.html`、`需求.docx`、`需求.pdf`、`需求.txt`。
5. 已有 `requirement.md` 时直接使用，不转换、不覆盖。
6. 没有 `requirement.md` 但有受支持源文件时，转换为 `requirement.md`。
7. 无任何需求源文件时，返回清晰错误。
8. 将 normalizer 接入 analyze、mvp、generate-testcases 前置流程。

## 原型图边界说明

新增或更新文档，说明：

1. MarkItDown 转 Markdown 主要解决文本归一化。
2. Word/PDF 里的原型图转成 Markdown 后，当前文本链路只能看到图片链接、标题、说明或 alt 文本。
3. 当前 Runtime 不会自动理解图片里的按钮、字段、布局和交互。
4. 后续如需分析原型图，需要新增 prototype image analysis：提取图片、生成图片清单、调用视觉模型或人工补充说明，再进入需求分析。

建议新增：

`docs/architecture/prototype-image-analysis-plan.md`

## 测试要求

必须新增或更新测试，至少覆盖：

1. 旧 8 章节需求分析不能通过评审级质量门。
2. 少于 15 条用例不能通过质量门。
3. 有“用例类型”列不能通过质量门。
4. 有非法优先级不能通过质量门。
5. Skeleton 占位语不能通过质量门。
6. 已有 `requirement.md` 时 normalizer 不转换。
7. 只有 `requirement.txt` 时转换成 `requirement.md`。
8. `requirement.md` 已存在时不覆盖。
9. 无需求源文件时报错清晰。
10. analyze/mvp 流程可在 normalizer 后继续读取 `requirement.md`。

## 验收命令

完成后执行：

- `pip install -e .`
- `python scripts/validate_docs_consistency.py`
- `python scripts/validate_prd_workspace.py prd/sample-login-requirement`
- `pytest`
- `ruff check .`
- `python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement --no-record-run`
- `python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --no-record-run`

## 完成回执

必须说明：

1. 质量门是否已升级。
2. MarkItDown 是否已接入。
3. normalizer 是否接入 analyze、mvp、generate-testcases。
4. 原型图当前能分析到什么程度。
5. pytest、ruff、文档校验结果。
