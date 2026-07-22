# Agentic-QA 文档

Agentic-QA v2 将开放式 QA 目标交给测试主管，专家 Agent 生成不可覆盖的 raw artifact。来源输入按
run 冻结，Normalizer 只处理表示形式，质量策略生成独立报告；Candidate 无论通过与否都会停在
Review Gate。只有人工显式选择通过质量门的版本并完成确定性 promote，产物才会发布。

```powershell
agentic-qa workspace create demo
agentic-qa run start demo "分析登录需求并生成测试用例"
agentic-qa run get demo <run_id>
agentic-qa run review demo <run_id> approve --artifact all `
  --variant testcases=raw --reason "人工审核通过" --reviewed-by qa-owner
```

推荐依次阅读：[配置](configuration.md)、[公开契约](harness-contracts.md)、
[架构](architecture.md)、[Review Gate](review-gate.md) 和
[工作区与产物版本](artifact-versioning.md)。
