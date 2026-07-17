# Harness 可靠性

每次 run 保存 task、plan、state、events 和增量 checkpoint。完成任务 ID 保存在快照中；
keyed tool call 保存独立记录，恢复时返回已记录结果而不重复外部动作。

默认预算：24 次模型调用、50 次工具调用、3 次重规划、3 个并发 Agent、30 分钟。
超限或无法完成时生成 partial 候选和明确错误，不写成完成。候选与 published 更新使用
原子文件替换；发布历史以 run_id 幂等。
