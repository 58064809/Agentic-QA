# 配置目录说明

当前 Harness 不读取旧 `configs/config.yaml` 或 `configs/local.yaml`。它们是旧 Runtime 的本地
遗留文件，继续忽略且不迁移。

当前配置来源只有：

- `.env.example` 所列模型和测试环境变量；
- `src/harness/manifests/` 中的 Agent、Skill 和 Tool 声明；
- `TaskRequest.execution_profile` 中的单次执行限制。

未来若增加可共享配置，应提交 `*.example.yaml`；包含本机路径、服务地址或凭证引用的
`configs/*.yaml` 仍保持本地。
