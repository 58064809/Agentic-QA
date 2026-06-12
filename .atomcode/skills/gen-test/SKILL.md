---
name: gen-test
description: 按 Agentic-QA 项目规范生成 pytest 测试文件（单元测试 + 集成测试）
version: v2.0
last_updated: 2025-07-19
user_invocable: true
disabled_model_invocation: false
related_skills: [project-conventions, code-reviewer]
---

# gen-test — 测试生成 Skill (v2.0)

## 概述

根据 Agentic-QA 项目约定，为指定模块生成 pytest 测试文件。覆盖单元测试和集成测试两种场景，遵循 `project-conventions` Skill 中的测试命名和目录规范。

## 工作流程

```
读目标代码 → 分析接口/功能 → 确定测试类型 → 编写测试 → 验证可运行
```

1. **读目标代码** — 确认 `.py` 文件路径和模块结构
2. **分析接口** — 提取需要测试的类、函数、方法签名
3. **确定测试类型** — `unit`（纯逻辑）或 `integration`（依赖外部资源）
4. **编写测试** — 输出完整 pytest 文件
5. **验证** — `pytest tests/<type>/test_<target>.py -v --tb=short`

## 文件路径规范

```
tests/unit/test_<module>.py         # 单元测试
tests/integration/test_<module>.py  # 集成测试
tests/conftest.py                    # 共享 fixtures（如已存在则追加）
```

## 代码结构模板

### 单元测试模板

```python
"""Tests for <module> — <brief description>."""

import pytest
from <module> import <target_class_or_function>


class Test<Target>:
    """<Target> 功能测试."""

    def test_<happy_path_scenario>(self):
        """应该正常处理基本功能."""
        ...

    @pytest.mark.parametrize("input_val,expected", [
        ("normal_input", "expected_output"),
        ("edge_case", "edge_output"),
    ])
    def test_<parametrized_scenario>(self, input_val, expected):
        """参数化测试：输入/输出对照."""
        ...

    def test_<error_scenario>(self):
        """异常输入应该抛出预期异常."""
        with pytest.raises(<ExpectedException>, match="预期错误消息"):
            ...
```

### 集成测试模板

```python
"""Integration tests for <module> — depends on LLM / network / filesystem."""

import pytest
import json
from pathlib import Path


@pytest.mark.integration
class Test<Target>Integration:
    """<Target> 集成测试."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """每个测试前准备临时目录，测试后清理."""
        self.work_dir = tmp_path / "test_work"
        self.work_dir.mkdir()
        yield
        # teardown: tmp_path 自动清理

    def test_<scenario>_with_real_data(self, tmp_path):
        """使用真实数据文件测试完整流程."""
        data_file = tmp_path / "input.json"
        data_file.write_text(json.dumps({"key": "value"}))
        ...
```

## Fixture 使用规范

### 优先使用内置 fixture（不要重复造轮子）

| 内置 fixture | 用途 | 示例 |
|-------------|------|------|
| `tmp_path` | 临时目录，测试后自动删除 | 写输出文件 |
| `tmp_path_factory` | 跨 session 的临时目录 | 共享缓存 |
| `capsys` | 捕获 stdout/stderr | 测试 CLI 输出 |
| `monkeypatch` | 临时修改环境变量/属性 | mock 外部依赖 |
| `caplog` | 捕获日志输出 | 验证日志级别 |

### 项目级共享 fixture（`tests/conftest.py`）

```python
import pytest
from pathlib import Path

@pytest.fixture
def sample_prd_path(tmp_path) -> Path:
    """创建一个 PRD 产物的最小目录结构."""
    prd_dir = tmp_path / "prd" / "T001"
    (prd_dir / "analysis").mkdir(parents=True)
    (prd_dir / "cases").mkdir()
    (prd_dir / "workspace.yml").write_text(
        "id: T001\ntitle: 示例需求\nstatus: draft\n"
    )
    return prd_dir

@pytest.fixture
def mock_env_vars(monkeypatch):
    """安全设置测试用环境变量."""
    monkeypatch.setenv("FREEMODEL_API_KEY", "test-key-123")
    monkeypatch.setenv("FREEMODEL_MODEL", "test-model")
```

## Mock 使用规范

### 原则

- **mock 外部**（网络、数据库、文件系统）但不 mock 被测试模块自身
- 使用 `unittest.mock`（pytest 内置）
- 复杂 mock 用 `monkeypatch` fixture 而非 `patch` 装饰器

### 示例

```python
from unittest.mock import Mock, patch

def test_use_llm_fallback_when_api_fails(mock_env_vars):
    """API 调用失败时应降级为规则模式."""
    with patch("runtime.llm_client.chat.completions.create") as mock_api:
        mock_api.side_effect = ConnectionError("API 不可达")
        result = run_analysis(use_llm=True)
        assert result["mode"] == "fallback_rule"
        assert "降级提示" in result["logs"]
```

## 断言规范

| 断言内容 | 推荐用法 | 避免 |
|----------|----------|------|
| 返回值相等 | `assert result == expected` | `assert True` |
| 包含元素 | `assert item in collection` | `assert result != None` |
| 字符串包含 | `assert "预期" in output` | |
| 异常 | `pytest.raises(ValueError, match="...")` | |
| 近似值 | `assert abs(实际 - 预期) < 0.001` | |
| 目录/文件存在 | `assert output_path.exists()` | |

## 输出检查清单

生成测试文件后，运行以下检查（或在终端手动执行）：

```bash
# 检查语法
python -m compileall tests/unit/test_<target>.py

# 运行测试
pytest tests/unit/test_<target>.py -v --tb=short

# 检查是否可以通过 lint
ruff check tests/unit/test_<target>.py
```

## 跨 Skill 引用

- [project-conventions](../project-conventions/SKILL.md) — 目录结构、命名规范
- [code-reviewer](../code-reviewer/SKILL.md) — 审查生成的测试是否符合规范
