# Agentic-QA

Agentic-QA 将开放式 QA 目标交给测试主管，由主管动态选择专家、并行执行、生成候选，
然后在硬 Review Gate 暂停。人工审核通过后才会发布。

```powershell
agentic-qa workspace init demo
agentic-qa run demo "分析登录需求并生成测试用例"
```

从[架构](architecture.md)、[Harness 契约](harness-contracts.md)和
[Review Gate](review-gate.md)开始阅读。
