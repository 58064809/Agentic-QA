# 产物版本与历史追溯

修订工作流不得直接覆盖正式产物。Runtime 必须先生成候选版本，经过质量检查和确认门禁后，才允许将候选版本提升为当前正式版本。旧版本进入 `artifacts/history/`，并在版本索引中标记为 `superseded`。

## 路径约定

```text
artifacts/testcases.md
artifacts/history/testcases/testcases.v1.md
artifacts/history/testcases/testcases.v2.md
artifacts/history/testcases/index.yml
runs/<run-id>/artifact-preview.md
runs/<run-id>/testcases.preview.md
runs/<run-id>/requirement-analysis.preview.md
runs/<run-id>/diff.md
runs/<run-id>/quality-check.json
```

`artifacts/testcases.md` 始终代表当前生效版本。`runs/<run-id>/<artifact>.preview.md` 是候选正文，`runs/<run-id>/artifact-preview.md` 只作为本次 run 的候选索引；确认通过前不得覆盖正式产物。

## 发布流程

```text
用户提出修订意见
  ↓
意图识别为 request_changes / revise_artifact
  ↓
读取当前正式产物
  ↓
生成 <artifact>.preview.md、artifact-preview.md 索引与 diff.md
  ↓
质量检查
  ↓
确认门禁
  ↓
确认通过后发布为新版本
```

确认通过后：

```text
artifacts/testcases.md -> 归档为 artifacts/history/testcases/testcases.vN.md
runs/<run-id>/testcases.preview.md -> 提升为 artifacts/testcases.md
artifacts/history/testcases/index.yml -> 追加版本记录
reviews/testcases.review.yml -> 更新状态
metadata.yml -> 更新 current_versions
```

## 版本索引示例

```yaml
artifact: artifacts/testcases.md
artifact_type: testcases
current_version: v3
versions:
  - version: v1
    path: artifacts/history/testcases/testcases.v1.md
    run_id: 20260612-150000-demo
    status: superseded
    created_at: "2026-06-12T15:00:00+08:00"
    source_message: "分析这个需求并生成测试用例"
  - version: v2
    path: artifacts/history/testcases/testcases.v2.md
    run_id: 20260612-153000-demo
    status: superseded
    created_at: "2026-06-12T15:30:00+08:00"
    source_message: "补充支付失败和库存不足场景"
  - version: v3
    path: artifacts/testcases.md
    run_id: 20260612-160000-demo
    status: current
    created_at: "2026-06-12T16:00:00+08:00"
    source_message: "测试用例确认通过，可以作为正式版本"
```

## metadata.yml 当前版本

```yaml
artifacts:
  testcases:
    current_path: artifacts/testcases.md
    current_version: v3
    history_index: artifacts/history/testcases/index.yml
    latest_run_id: 20260612-160000-demo
    status: confirmed
```

## 产物状态

| 状态 | 含义 |
|---|---|
| `draft` | 草稿生成中或尚未进入确认 |
| `partial` | 只生成部分内容，不能作为正式产物 |
| `needs_human_review` | 等待用户通过 Chat / Bot / CLI 确认 |
| `approved` | 已确认通过，可进入下一步 |
| `needs_changes` | 需要修订后重新确认 |
| `rejected` | 当前产物不可用，需要重新生成或废弃 |
| `confirmed` | 已完成最终确认，可作为正式测试资产 |
| `archived` | 已归档 |
| `failed` | 生成失败，仅保留错误上下文和中间结果 |
| `superseded` | 已被新版本产物替代 |
