# 开始使用

## 1. 创建唯一配置文件

在仓库根目录执行：

```powershell
python -m harness config init
```

然后打开根目录一眼可见的 `agentic-qa.local.yml`。所有需要人工填写的持久配置都在这里：API 环境和
Base URL、手机号/账号、验证码、AES Key、Token、PostgreSQL、TestRail、Qase、模型/RAG 非密钥参数。
只有模型实际 Key 和 RAG 实际 Key 仍放环境变量。

至少完成以下检查：

1. `model.api_key_env` 指向当前 PowerShell 已设置的模型 Key。
2. `postgres.password` 不为空。
3. `api.services.<服务>.source_directory` 指向真实来源目录。
4. 目标环境的 `base_url`、`trusted_origins`、允许方法和认证完整。
5. 使用登录时填完所有字段；暂不登录时清空所有登录值并填写 `fallback_token`。

```powershell
$env:DEEPSEEK_API_KEY = "<模型 Key>"
$env:RAG_API_KEY = "<仅远程 RAG 需要>"
python -m harness config doctor
```

从旧版配置升级时先执行一次 `python -m harness config secrets migrate`。敏感值会集中到文件顶部
`secrets.values`，业务配置只保留 `secret://` 引用；CI 可改用 environment provider。模型和远程 RAG
的实际 Key 仍由 `api_key_env` 指向环境变量。

任何必要项缺失都会准确报告 `agentic-qa.local.yml` 的字段路径，并在产生 workspace、run 或模型调用前
终止。

## 2. 放入真实 API 来源

每个服务使用固定目录：

```text
local-sources/api/<service>/
├─ member-service.json        # 自包含 Apifox/OpenAPI 3.x 或 Swagger 2.0
└─ test-cases.csv             # 11 列人工用例；也可用 Markdown/TestCaseSet YAML
```

服务目录不再放 `api-test.yml`。根配置中的 `source_directory` 与目录采用精确匹配。其他文件会列入
ignored 清单，不发送给模型。

## 3. 目录到 Candidate

```powershell
python -m harness api doctor .\local-sources\api\member-service --environment dev
python -m harness api prepare .\local-sources\api\member-service --environment dev
```

`api prepare` 只做单 API Agent 场景组装并生成 Candidate，绝不自动批准或执行。完整 OpenAPI 在本地
解析，模型只看到规范化 operation/Schema；人工用例通过 `manual-test-case` source refs 保持追踪。

## 4. 人工 Review

先查看差异，再选择明确版本批准：

```powershell
python -m harness run diff <workspace> <run> api_test_draft --before raw --after normalized
python -m harness run review <workspace> <run> approve `
  --artifact api_test_draft `
  --variant api_test_draft=raw `
  --reason "人工确认接口、数据与清理步骤" `
  --reviewed-by qa_owner
```

执行入口只接受无 partial、blocker、来源缺口或哈希漂移的已审核版本。审核后的
`agentic-qa.api-cases.v1.2` YAML 是唯一事实来源；pytest 只是确定性执行壳。

## 5. 受控 QA 试跑

```powershell
python -m harness api run <workspace> trial-001 --environment dev
```

相同 execution ID 永不重放。结果写入：

```text
workspaces/<workspace>/executions/trial-001/
├─ manifest.json
├─ execution-plan.json
├─ evidence.json
├─ execution-events.jsonl
├─ report-summary.json
├─ cleanup-summary.json
├─ .cleanup-journal.enc          # 有 cleanup 时存在
├─ allure-results/
├─ allure-report/
├─ triage/collections/            # 显式 failure collect 后按 collection 建立
└─ summary.md
```

workspace 根目录的 `allure-history.jsonl` 由 Allure 3 维护，用于后续执行的趋势、回归和 flaky 展示。

只包含 passed/skipped 且 cleanup 完成时返回 0；存在 failed/broken 或未完成 cleanup 返回 1；配置或命令错误返回 2。
报告阶段采用 best-effort 隔离：执行事实已提交后，即使报告写入失败也不改变测试结论。
`allure-results`、HTML、Markdown 和报告汇总的返回路径以实际生成产物为准；本地未安装 Allure CLI 时通常
保留 results 并标记 `results_only`。执行 `npm ci` 后可生成 HTML，也可稍后运行：

```powershell
python -m harness api report allure <workspace> trial-001
```

中途崩溃保存 `indeterminate`；如果 mutation 已在发送边界，则保存 `cleanup_indeterminate` 和加密的
`armed` obligation，要求人工核对环境。业务请求和 `armed` cleanup 均不自动重放。只有已确认从未发送的
`pending` cleanup 可以显式恢复：

```powershell
python -m harness api cleanup resume <workspace> trial-001 --environment dev
```

报告和结构化日志不保存响应原值、Token、Cookie、请求业务值或配置凭据。

失败实例需要日志辅助定位时，继续阅读 [Failure Triage](failure-triage.md)。日志不会随 API 执行自动
拉取，显式 collect/analyze/report 也不会修改原 execution 的四套状态。

## 6. 导出确定性 pytest 壳

```powershell
python -m harness api export-pytest <workspace>
pytest workspaces/<workspace>/exports/api_test_draft/test_api_cases.py -q
```

导出时已绑定审核环境，运行时通过 Harness 重新读取根配置，不需要 `AGENTIC_QA_BASE_URL`、
`AGENTIC_QA_EXECUTION_ENVIRONMENT` 或其他 API 环境变量。
