---
version: v2.0
last_updated: 2025-07-19
difficulty: ★★☆☆☆
category: output
related_methods:
  - api-contract-analysis-skill
  - equivalence-partitioning-skill
  - boundary-value-analysis-skill
tags: [pytest, API测试, 自动化脚本]
---

# pytest API 测试技能

## 概述

使用 pytest 框架将 API 用例转化为可执行的自动化草稿，包括 fixture 管理、参数化、断言策略和环境安全规范。

## 适用时机

- API 契约分析和用例设计已完成
- 需要将手工 API 用例自动化

## 前置知识

- 掌握 pytest 基础（fixture、parametrize、conftest）
- 了解 HTTP 请求库（requests / httpx）
- 接口文档已解析（`api-contract-analysis-skill.md`）

## 操作步骤

### Step 1: 建立 fixture 体系

```python
# conftest.py
import pytest
import os

@pytest.fixture(scope="session")
def base_url():
    url = os.getenv("API_BASE_URL")
    if not url:
        pytest.skip("API_BASE_URL 未设置")
    return url

@pytest.fixture(scope="session")
def auth_token(base_url):
    resp = requests.post(f"{base_url}/auth/login", json={
        "phone": os.getenv("TEST_PHONE"),
        "password": os.getenv("TEST_PASSWORD"),
    })
    assert resp.status_code == 200
    return resp.json()["token"]
```

### Step 2: 参数化覆盖等价类和边界值

```python
@pytest.mark.parametrize("phone,expected_code", [
    ("13800138000", "SUCCESS"),      # 有效等价类
    ("12345678901", "SUCCESS"),      # 其他有效号段
    ("", "PARAM_MISSING"),           # 空值无效类
    ("abc", "FORMAT_ERROR"),         # 格式错误无效类
    ("1380013800", "FORMAT_ERROR"),  # 边界 N-1（边界值）
])
def test_login_phone_validation(base_url, phone, expected_code):
    resp = requests.post(f"{base_url}/auth/login", json={
        "phone": phone,
        "password": "validPass123",
    })
    assert resp.json()["code"] == expected_code
```

### Step 3: 明确断言策略

| 断言类型 | 示例 | 说明 |
|---------|------|------|
| HTTP 状态码 | `assert r.status_code == 200` | 网络层面是否正确 |
| 业务码 | `assert r.json()["code"] == "SUCCESS"` | 业务逻辑是否正确 |
| 字段值 | `assert r.json()["data"]["token"] is not None` | 关键字段存在 |
| 枚举值 | `assert status in ("ACTIVE", "LOCKED")` | 字段值合法 |
| 响应结构 | `assert set(r.json().keys()) >= {"code", "message"}` | 结构完整性 |

### Step 4: 安全保护

| 规则 | 做法 |
|------|------|
| 不硬编码密钥 | 从环境变量读取，.env.example 占位 |
| 不加默认生产地址 | URL 为空时 `pytest.skip()`，不默认走 localhost |
| 测试数据隔离 | 使用独立测试账号，不混合生产数据 |

## 输出模板

### 文件结构

```
tests/
├── conftest.py              # 全局 fixtures
├── test_auth.py             # 认证模块
│   ├── test_login_success.py
│   ├── test_login_validation.py
│   └── test_login_lock.py
├── test_users.py            # 用户模块
└── utils/
    ├── client.py            # 封装的 HTTP client
    └── data.py              # 测试数据
```

## 自检清单

| 检查项 | 通过标准 | 自查 |
|--------|----------|:----:|
| pytest 可收集 | `pytest --collect-only` 无报错 | □ |
| 环境变量保护 | 敏感值从环境变量读取，无硬编码 | □ |
| 默认安全 | URL 为空时 skip 而非连默认地址 | □ |
| 断言完整 | HTTP 状态码 + 业务码 + 字段三者齐全 | □ |
| 参数化覆盖 | 等价类和边界值已参数化 | □ |
| skip 保护 | 依赖缺失时 skip 而非 fail | □ |

## 常见误区

- ❌ 默认请求 localhost 或生产地址
- ❌ 缺少环境变量时测试直接失败而不是 `pytest.skip`
- ❌ 断言只检查 HTTP 200，忽略业务码和字段内容
- ❌ 敏感配置（密码、token）硬编码在代码中

## FAQ

**Q: fixture scope 怎么选？**
A: 一般 `session`（base_url、auth_token）、`class`（一组用例共享）、`function`（每个用例独立）。不共享的数据用 `function`。

**Q: 测试数据怎么管理？**
A: 简单数据写在 `@pytest.mark.parametrize` 中；复杂数据集放在 `tests/utils/data.py` 或 JSON/YAML 文件中。

## 关联方法

- `api-contract-analysis-skill.md` — 契约分析的断言点作为脚本依据
- `equivalence-partitioning-skill.md` — 参数化数据来源
- `boundary-value-analysis-skill.md` — 参数化数据来源

## 参考标准

- pytest 官方文档
- requests / httpx 库文档
