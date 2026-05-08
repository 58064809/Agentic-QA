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

## 任务列表

- `001-bootstrap-final-workspace.md`：一次性初始化最终版工作区骨架、规则、工作流、Agent、Prompt、Rules、Skills、PRD 示例、脚本、CI。
- `002-enhance-content-quality.md`：补强各类文档、Prompt、Rules、Skills、Knowledge 的内容质量。
- `003-validate-and-polish.md`：执行校验、修复问题、完善 README 和使用示例。

## 当前建议执行顺序

先把 `001-bootstrap-final-workspace.md` 交给 Codex 执行。

执行完成后，先跑验收命令，再继续执行后续任务。
