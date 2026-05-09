# 任务 007：接入 GitHub Actions 自动校验

## 任务目标

在 006 已新增轻量文档一致性检查脚本后，把仓库基础校验接入 GitHub Actions，让后续每次 push 到 `master` 或创建 PR 时，GitHub 自动执行文档一致性检查、PRD 工作区校验、单元测试和 Ruff 静态检查。

本任务目标不是搭建复杂 CI/CD 平台，而是补齐最小可用的自动验收能力，减少每次人工确认“有没有跑测试”的成本。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 尽量不自研，不创建 Runtime、LLM Provider、LangGraph、LangChain、LiteLLM、`agentic_qa/` 或 `src/agentic_qa/`。
4. 工程脚本仍只放 `scripts/`。
5. GitHub Actions workflow 保持简单、清晰、可维护。
6. 不接入生产环境、不访问真实业务接口、不需要任何 secret。
7. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 背景

目前仓库已经有：

- `scripts/validate_docs_consistency.py`
- `scripts/validate_prd_workspace.py`
- `scripts/run_pytest.py`
- `pytest`
- `ruff check .`

但 GitHub 上还没有可见的 status checks 或 workflow runs。后续每次任务完成后，只靠 Codex 本地回执仍然不够可靠。

007 要把这些基础命令接入 GitHub Actions，形成最小自动验收闭环。

## 具体任务

### 1. 新增 GitHub Actions workflow

新增：

`.github/workflows/ci.yml`

建议内容：

```yaml
name: CI

on:
  push:
    branches:
      - master
  pull_request:
    branches:
      - master

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install package
        run: pip install -e .

      - name: Validate docs consistency
        run: python scripts/validate_docs_consistency.py

      - name: Validate sample PRD workspace
        run: python scripts/validate_prd_workspace.py prd/sample-login-requirement

      - name: Run pytest wrapper
        run: python scripts/run_pytest.py

      - name: Run pytest
        run: pytest

      - name: Run ruff
        run: ruff check .
```

要求：

- workflow 名称简洁，例如 `CI`。
- 只使用成熟官方 action：`actions/checkout`、`actions/setup-python`。
- 不配置 secret。
- 不运行真实业务接口测试。
- 不上传复杂报告，先保持最小可用。

### 2. 更新 README

在 `快速开始` 或项目说明中补充：

- GitHub Actions 会在 push 到 `master` 和 PR 时自动运行基础校验。
- 当前 CI 包含：
  - 文档一致性检查
  - sample PRD 工作区校验
  - pytest wrapper
  - pytest
  - ruff
- CI 不会访问真实业务环境，也不依赖 secret。

### 3. 更新完成回执或规则引用说明

如有必要，可以轻微更新：

- `rules/codex-output-rules.md`
- `knowledge/templates/codex-completion-summary-template.md`

但不要大改 005 内容。只需确保完成回执中的“验收结果”能够记录：

- 本地命令结果
- GitHub Actions 是否通过
- 未执行时必须说明原因

### 4. 可选：补充文档一致性检查覆盖 workflow

如果改动很小，可以让 `scripts/validate_docs_consistency.py` 也检查：

- `.github/workflows/ci.yml` 存在。

但注意：

- 不要写复杂 YAML 解析。
- 如果只是检查文件是否存在即可，保持轻量。

### 5. 可选：补充测试

如果调整了 `validate_docs_consistency.py`，需要同步更新单元测试。

例如：

- 当前仓库文档一致性检查通过。
- 缺少 `.github/workflows/ci.yml` 时能够报错。

如果没有调整脚本，则不强制新增测试。

## 验收命令

本地执行：

```bash
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/sample-login-requirement
python scripts/run_pytest.py
pytest
ruff check .
```

提交后，还需要检查 GitHub Actions：

- 是否出现 `CI` workflow run。
- workflow 是否通过。

如果 GitHub Actions 未触发或未执行，完成回执中必须说明原因，不能写成通过。

## 提交要求

直接提交到 `master`。

Commit message：

```text
chore: add github actions validation
```

## 完成后的回复要求

必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复，只输出摘要，不粘贴完整文件或完整 diff。

回执里的验收结果必须区分：

- 本地命令是否通过。
- GitHub Actions 是否触发。
- GitHub Actions 是否通过。
- 未执行或未看到结果时，必须写明原因。
