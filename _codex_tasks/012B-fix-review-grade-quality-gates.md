# 任务 012B：修复 012/012A 评审级质量门未落地问题

## 任务背景

012 已打通需求分析、测试用例生成和 MVP 连续链路；但审核发现：012A 要求的“领导评审级输出质量”没有真正落地。当前实现仍然允许 Skeleton 占位内容通过质量检查，测试用例只要有表头和 needs_human_review 就能通过，这不满足真实产品需求评审要求。

本任务必须在 012 基础上修复质量门，确保周一真实需求输出不是玩具草稿，而是可给领导、产品、开发和测试评审的专业 QA 产物。

## 审核发现的问题

### 问题 1：需求分析质量门过低

当前 `runtime/graph/nodes/mvp_quality.py` 只检查以下 8 个基础章节：

```text
需求概述
业务规则
流程拆解
角色与权限
数据与状态
异常与边界
风险点
待确认问题
```

但 012A 要求必须包含 12 个评审级章节：

```text
需求背景与目标
业务范围
角色与权限
主流程拆解
分支流程与异常流程
业务规则清单
数据字段与状态流转
接口与依赖系统
测试范围建议
风险点与影响面
待确认问题
需求到测试覆盖映射
```

### 问题 2：测试用例质量门过低

当前测试用例质量检查只检查：

- `needs_human_review`
- 表头：标题、优先级、前置条件、测试步骤、预期结果
- 输出路径

但没有检查：

- 至少 15 条非表头用例。
- 是否包含 P0 用例。
- 是否覆盖主流程、异常、边界、权限、状态、数据一致性等关键场景。
- 是否仍包含 Skeleton 占位语。
- 是否所有优先级都在 P0/P1/P2/P3 范围内。

### 问题 3：Skeleton 内容仍然能通过

当前 `render_testcase_skeleton()` 只有 3 条用例，而且包含大量“待补充”“待确认”。当前质量门仍会让它通过。真实评审场景不能这样。

### 问题 4：Prompt 仍然偏 MVP，不是评审级

`runtime/llm/prompt_builder.py` 中需求分析 Prompt 只要求 8 个基础章节；测试用例 Prompt 没有明确要求不少于 15/30/50 条，也没有要求覆盖主流程、权限、状态、异常、边界、幂等、数据一致性、兼容、回归影响等。

### 问题 5：LLM Adapter 使用 chat.completions，用户验证的是 responses.create

用户本地验证通过的是 OpenAI-compatible `responses.create` 调用。当前 adapter 使用 `client.chat.completions.create`。这不一定错，但为了兼容用户已验证链路，建议优先使用 `responses.create`，如果不可用再 fallback 到 `chat.completions.create`。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不提交密钥、`.env`、`.venv/`、`.runtime/runs/`。
4. LLM 默认关闭，只能通过 `--use-llm` 显式启用。
5. 不执行真实测试，不生成 API/UI 自动化脚本，不归档。
6. 不覆盖已有人工审核产物。
7. 修复后必须保证 Skeleton 低质量内容不能被误判为评审级通过。
8. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 修复要求

### 1. 更新需求分析输出模板

更新 `render_requirement_analysis_skeleton()` 和 LLM Prompt，使需求分析输出固定包含 12 个章节：

```markdown
# 需求分析草稿

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
```

Skeleton 可以保留，但必须明确标记为“信息不足，仅供补充材料”，并且默认不应该通过评审级质量门，除非用户只是 dry-run 且没有 `--use-llm`。

### 2. 更新需求分析质量检查

需求分析质量检查至少检查：

- `needs_human_review`。
- 12 个必要章节全部存在。
- `待确认问题` 下至少有 3 个具体问题。
- `业务规则清单` 不能只有一个“待补充”。
- `风险点与影响面` 不能为空。
- `需求到测试覆盖映射` 必须存在表格或列表。

### 3. 更新测试用例 Prompt

测试用例 Prompt 必须明确要求：

- 固定列：标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果。
- 不新增“用例类型”列。
- 简单需求不少于 15 条，中等需求不少于 30 条，复杂需求不少于 50 条。
- 必须包含 P0 用例。
- 必须覆盖主流程、分支流程、权限、状态流转、必填/格式/边界、异常、重复提交/幂等、数据一致性、老数据兼容、前后端一致性、依赖失败、回归影响范围。
- 每条预期结果必须可验证。

### 4. 更新测试用例质量检查

测试用例质量检查至少检查：

- `needs_human_review`。
- 固定表头存在。
- 表格列数正确，不允许多出“用例类型”。
- 至少 15 条非表头用例；如果不足 15 条，必须返回 quality_errors。
- 至少 1 条 P0。
- 优先级只能是 P0/P1/P2/P3。
- 不允许出现以下占位语并通过：
  - `待接入 LangChain 后生成`
  - `待补充：基于需求主流程生成`
  - `待确认账号和数据`
  - `结果符合需求`
  - `待补充：边界条件验证`
- 必须覆盖至少 4 类场景关键词：主流程、异常、边界、权限、状态、幂等、数据一致性、兼容、回归、接口、消息、日志、审计。

### 5. Skeleton 生成策略

如果未启用 LLM 或缺少密钥，仍允许生成 Skeleton，但要明确：

- `result.success` 可以为 false 或带 `quality_errors`，提示“Skeleton 不满足评审级质量，请使用 --use-llm 或补充 PRD”。
- 不应该让用户误以为 Skeleton 已可评审。
- CLI 输出必须能显示 quality_errors。

### 6. LLM Adapter 兼容用户已验证调用方式

更新 `runtime/llm/openai_compatible.py`：

- 优先尝试 `client.responses.create(model=..., input=...)`。
- 如果 SDK 或服务不支持，再 fallback 到 `client.chat.completions.create(...)`。
- 不记录 API Key。
- 单测必须 mock，不真实调用外部 API。

### 7. 测试补充

更新或新增测试，至少覆盖：

1. Skeleton 测试用例少于 15 条时会产生 quality_errors。
2. Skeleton 占位语不能通过评审级测试用例质量门。
3. 需求分析缺少 12 章节时会产生 quality_errors。
4. 需求分析包含 12 章节但待确认问题为空时会产生 quality_errors。
5. 测试用例包含“用例类型”列时会产生 quality_errors。
6. 测试用例存在非法优先级如 P4 时会产生 quality_errors。
7. LLM 生成 15 条以上合格用例时可以通过质量门。
8. Adapter 优先调用 `responses.create`。
9. Adapter 在 responses 不可用时 fallback 到 chat completions。

## 验收命令

完成后尽量执行：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement --no-record-run
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/sample-login-requirement --no-record-run
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --no-record-run
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/sample-login-requirement
pytest
ruff check .
```

如果本地已配置密钥，可额外验证：

```bash
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --use-llm --no-record-run
```

注意：不要提交 `.runtime/runs/`、`.venv/`、`.env` 或任何密钥文件。

## 完成回执要求

完成后必须说明：

1. 是否已补齐 12 章节需求分析质量门。
2. 是否已补齐不少于 15 条用例质量门。
3. 是否已禁止 Skeleton 占位内容误通过。
4. 是否已支持 responses.create 优先调用。
5. 是否执行了 pytest 和 ruff。
6. 周一真实需求建议使用的命令。
