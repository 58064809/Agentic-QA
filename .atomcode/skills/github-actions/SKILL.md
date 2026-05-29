---
name: github-actions
description: GitHub Actions workflow 编写和维护指南 — CI/CD 管道、缓存策略、矩阵构建、安全扫描
version: v2.0
last_updated: 2025-07-19
user_invocable: true
disabled_model_invocation: false
related_skills: [project-conventions, code-reviewer]
---

# GitHub Actions Skill (v2.0)

## 概述

维护 Agentic-QA 项目的 GitHub Actions CI/CD。项目已有 2 个 workflow，本 skill 提供实战级模板和最佳实践。

## 项目现有 Workflows

| 文件 | 触发条件 | 作用 |
|------|----------|------|
| `.github/workflows/ci.yml` | push → master, PR → master | 文档一致性检查 + pytest + ruff |
| `.github/workflows/qa-check.yml` | PR → master | PR 标题格式检查 |

## 编写规范

| 配置项 | 值 |
|--------|-----|
| Runner | `ubuntu-latest` |
| Python | `"3.11"` |
| 安装 | `pip install -e .` |
| 安全检查 | 不连接生产服务、不依赖 secret（除非必须） |
| 安全密钥 | 敏感值通过 `${{ secrets.XXX }}` 引用 |

## 实战模板

### 1. 标准 CI（含依赖缓存 + 并行矩阵）

```yaml
name: CI

on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
          cache-dependency-path: pyproject.toml
      - run: pip install -e .
      - run: ruff check .

  test:
    needs: lint
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
      fail-fast: false
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: "pip"
          cache-dependency-path: pyproject.toml
      - run: pip install -e .
      - run: pytest tests/ -v --tb=short --junitxml=report-${{ matrix.python-version }}.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-reports-${{ matrix.python-version }}
          path: report-*.xml

  coverage:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - run: pip install -e .
      - run: pip install pytest-cov
      - run: pytest tests/ --cov=runtime --cov=agents --cov-report=term-missing
      - run: |
          coverage=$(pytest tests/ --cov=runtime --cov-report=term 2>&1 | grep "TOTAL" | awk '{print $4}' | tr -d '%')
          if [ "$coverage" -lt 80 ]; then
            echo "❌ 覆盖率 ${coverage}% < 80%"
            exit 1
          fi
          echo "✅ 覆盖率 ${coverage}% ≥ 80%"
```

### 2. 按需手动触发（workflow_dispatch）

```yaml
name: Manual QA Run

on:
  workflow_dispatch:
    inputs:
      prd_id:
        description: "PRD ID（如 T001）"
        required: true
        type: string
      use_llm:
        description: "启用 LLM 分析"
        required: false
        default: false
        type: boolean

jobs:
  run_qa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e .
      - run: |
          cmd="agentic-qa analyze ${{ inputs.prd_id }}"
          if [ "${{ inputs.use_llm }}" = "true" ]; then
            cmd="$cmd --use-llm"
          fi
          eval "$cmd"
      - uses: actions/upload-artifact@v4
        with:
          name: qa-report-${{ inputs.prd_id }}
          path: prd/${{ inputs.prd_id }}/80-reports/
```

### 3. 文档一致性检查

```yaml
name: Doc Consistency

on:
  pull_request:
    paths:
      - "*.md"
      - "prompts/**"
      - "rules/**"

jobs:
  check-links:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e .
      # 调用项目内置的文档校验
      - run: agentic-qa check-docs --strict
```

### 4. PR 标题检查（已有 `qa-check.yml` 模板）

```yaml
name: PR Title Check

on:
  pull_request:
    types: [opened, edited, synchronize]

jobs:
  validate-pr-title:
    runs-on: ubuntu-latest
    steps:
      - name: 检查 PR 标题格式
        env:
          TITLE: ${{ github.event.pull_request.title }}
        run: |
          if echo "$TITLE" | grep -qE '^(feat|fix|docs|refactor|perf|test|ci|chore|revert)(\(.+\))?: .{1,100}$'; then
            echo "✅ PR 标题格式有效"
          else
            echo "❌ PR 标题格式无效"
            echo "预期格式: <type>(<scope>): <描述>"
            echo "type: feat|fix|docs|refactor|perf|test|ci|chore|revert"
            exit 1
          fi
```

## 缓存策略

| 缓存类型 | Key 生成 | 恢复时机 | 适用 Job |
|----------|----------|----------|----------|
| pip 依赖 | `pip-${{ hashFiles('pyproject.toml') }}` | setup-python 自动 | lint, test, coverage |
| pre-commit | `precommit-${{ hashFiles('.pre-commit-config.yaml') }}` | `actions/cache@v4` | lint |

## 安全指南

- ✅ 使用 `${{ secrets.XXX }}` 传递 API Key
- ✅ 仅在需要时设置 `env` 作用域，避免泄露
- ✅ artifact 上传带 `if: always()` 确保即使 job 失败也能看结果
- ❌ 不要在 step 中硬编码 token 或 key
- ❌ 不要用 `pull_request_target` 除非明确知道风险（代码注入）

## 跨 Skill 引用

- [project-conventions](../project-conventions/SKILL.md) — 项目构建、测试流程约定
- [code-reviewer](../code-reviewer/SKILL.md) — CI 中调用的检查工具规范
