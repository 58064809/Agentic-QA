# Codex 临时任务目录

本目录用于临时存放给 Codex 执行的施工任务书。

项目目标来自 ChatGPT 项目来源：`Agentic-QA` 是一个 **Command-routed Human-in-the-loop Agentic QA Workspace**，中文定位为 **指令路由型人机协同 Agentic QA 工作空间**。

## 使用规则

1. 本目录是临时目录，项目建设完成后可以删除。
2. Codex 执行任务时，优先读取本目录下对应任务文件。
3. 所有任务均要求直接在 `master` 分支开发，不创建新分支。
4. 生成文档尽量使用中文。
5. 尽量不自研，优先使用成熟工具和文件化规范。
6. 任务可以步子大一些，目标是尽快形成可用成果。
7. 项目正式说明文档是仓库根目录的 `README.md`，不在 `_codex_tasks/` 中维护。

## 任务列表

- `001-bootstrap-final-workspace.md`：一次性初始化最终版工作区骨架、规则、工作流、Agent、Prompt、Rules、Skills、PRD 示例、脚本、CI。
- `002-align-core-files.md`：对齐目录、核心文件、路径、状态、引用关系和验收命令。

## 当前建议执行顺序

按任务编号顺序执行已存在的任务文件；后续任务文件创建前，不在索引中预留不存在的任务引用。
