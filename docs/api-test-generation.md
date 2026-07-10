# 接口测试草稿生成

`api_test_draft` 是接口测试能力建设的第一阶段产物。Runtime 生成接口测试计划、断言策略、pytest + requests 脚本草稿，以及同一 Review Gate 下的 YAML 接口用例草稿；生成阶段不执行真实 HTTP 请求。

## 工作流

```text
需求 / 接口文档 / 已确认测试用例
  ↓
生成接口测试草稿和 YAML 接口用例草稿
  ↓
质量检查
  ↓
写入 runs/<run_id>/artifact-preview.md
写入 runs/<run_id>/api-test-cases.yml
  ↓
Review Gate
  ↓
promote 到 artifacts/api-test-draft.md
同步发布 artifacts/api-test-cases.yml
  ↓
pytest 在显式测试环境中读取 YAML 执行
```

## 输入

- `prd/<需求ID>/input/requirement.md`
- `prd/<需求ID>/input/api.md`：可选，有可用内容时优先作为接口事实来源。
- `prd/<需求ID>/input/api.openapi.json|yaml`：可选，Swagger/OpenAPI/Apifox 导出文件。
- `prd/<需求ID>/artifacts/requirement-analysis.md`：可选，提供业务规则和风险。
- `prd/<需求ID>/artifacts/testcases.md`：可选，提供已确认测试覆盖点。
- `prompts/api-test-generation.md`
- `skills/api-testing.md`

## OpenAPI / Swagger 导入

CLI 支持传入本地 OpenAPI / Swagger / Apifox 导出文件：

```bash
agentic-qa "基于 D:\api\activity-openapi.json 生成接口测试草稿，PRD 是 prd/5月活动玩法"
```

Runtime 会复制源文件到：

```text
prd/<需求ID>/input/api.openapi.json
```

并生成归一化 Markdown：

```text
prd/<需求ID>/input/api.md
```

如果工作区中已存在 `input/api.openapi.json`、`input/api.swagger.json`、`input/api.apifox.json`
或对应 YAML 文件，`api_test_draft` workflow 会先归一化，再生成草稿。

## 无接口文档规则

没有可用 `input/api.md` 时，Runtime 允许生成接口候选点，但必须标记：

```text
待补充接口文档
待确认 URL
待确认 Method
待确认请求字段
待确认响应字段
待确认鉴权方式
```

推断内容不得写成确定接口事实。

## 质量门

`api_test_quality_check_node` 至少检查：

- 输出包含接口清单。
- 输出包含接口测试点矩阵。
- 输出包含 pytest + requests 脚本草稿。
- 同 run 目录生成 `api-test-cases.yml`，schema_version 为 `agentic-qa.api-cases.v1.1`。
- YAML 用例包含 `business_rules` 和 `cases[].id/title/priority/contract_status/business_rule_refs/request/assertions/variables/cleanup/pending`。
- 新用例只允许使用嵌套 `request.method/path` 和类型化 `assertions`；旧 v1 仅保留读取兼容。
- YAML 用例不得写完整环境域名，base URL 只能通过 `AGENTIC_QA_BASE_URL` 注入。
- 输出包含断言策略。
- 无可用接口文档时包含“待补充接口文档”提示。
- 不出现“已执行 / 执行通过 / 实测通过”等执行结论。
- 不包含真实 token、Cookie 或密钥。

## 发布

候选内容先写入：

```text
prd/<需求ID>/runs/<run_id>/artifact-preview.md
prd/<需求ID>/runs/<run_id>/api-test-cases.yml
```

`api-test-cases.yml` 不是独立审核产物；它跟随 `api_test_draft` 一起进入候选、人工确认和 promote。未确认前只能位于 `runs/<run_id>/` 下，不能作为正式可执行用例来源。

Review Gate 审核通过后，才允许确定性 promote 到：

```text
prd/<需求ID>/artifacts/api-test-draft.md
prd/<需求ID>/artifacts/api-test-cases.yml
```

## Pytest 执行

确认并发布后，可通过现有 pytest 封装执行 YAML 接口用例：

```bash
$env:AGENTIC_QA_API_CASES_FILE="prd/<需求ID>/artifacts/api-test-cases.yml"
$env:AGENTIC_QA_BASE_URL="https://test.example.com"
$env:AGENTIC_QA_TEST_TOKEN="仅测试环境 token"
.venv\Scripts\python.exe scripts/run_pytest.py tests/api/test_yaml_api_cases.py
```

执行约束：

- 未设置 `AGENTIC_QA_API_CASES_FILE` 时，pytest 模块跳过。
- 未设置 `AGENTIC_QA_BASE_URL` 时，接口请求跳过。
- YAML 中的 token、base URL、Cookie 等只能通过 `${ENV_NAME}` 占位读取环境变量。
- 禁止默认连接生产环境、localhost 或任何隐式地址。
