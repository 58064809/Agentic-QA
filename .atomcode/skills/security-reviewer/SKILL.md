---
name: security-reviewer
description: 安全审查员 — 检查 API 密钥管理、路径安全、数据泄露、依赖风险、OWASP Top 10 合规
version: v2.0
last_updated: 2025-07-19
user_invocable: true
disabled_model_invocation: false
related_skills: [code-reviewer, project-conventions, github-actions]
---

# 安全审查员 (Security Reviewer) v2.0

## 审查范围

### 1. 凭据管理（P0 阻断）

- [ ] **硬编码密钥** — 扫描 `API_KEY`、`SECRET`、`token`、`password`、`credentials` 等关键词是否出现在 `.py` 中
- [ ] **.env 合规** — `.env` 在 `.gitignore` 中，不在 Git 历史中
- [ ] **安全传输** — API Key 仅通过环境变量或 `--key` CLI 参数传递，不在日志/输出中泄露
- [ ] **git 历史清理** — 是否曾有带密钥的文件被提交（`git log -p | grep API_KEY`）

### 2. 路径安全（Pl 警告）

- [ ] **路径穿越** — `open(user_input_path, ...)` 类代码是否校验路径范围
- [ ] **目录边界** — 所有文件写入在 `prd/<id>/` 或 `tests/` 等约定目录内
- [ ] **路径拼接** — 使用 `pathlib.Path` 而非 `os.path.join` + 字符串拼接
- [ ] **临时文件** — 使用 `tempfile` 或 `tmp_path`，而非自定义临时路径

### 3. 数据泄露（P1 警告）

- [ ] **日志脱敏** — 日志输出中是否包含 `request.headers`、`response.text` 等可能含敏感字段的内容
- [ ] **异常信息** — `traceback` 是否被返回给用户而非仅记录日志
- [ ] **报告导出** — QA 报告是否包含足以还原凭据的信息
- [ ] **LLM 上下文** — Prompt 中是否携带了 API Key 或其他敏感配置

### 4. 依赖安全（P2 建议）

- [ ] **已知漏洞** — `pip audit` 或 `safety check` 扫描已安装包
- [ ] **锁定版本** — `pyproject.toml` 中依赖是否指定了版本范围
- [ ] **可选依赖** — LLM 相关依赖是否标记为 `[optional]` 而非硬依赖

### 5. OWASP Top 10 对照

| OWASP 类别 | 项目风险点 | 检查方法 |
|------------|-----------|----------|
| A01 权限控制失效 | Agent 越权读取其它 PRD | 检查路径拼接是否锁定 `prd/<id>/` 范围 |
| A03 注入 | Prompt 注入 | `--user-prompt` 参数是否做输入验证 |
| A05 安全配置错误 | LLM 密钥未配置 | 启动时校验 `FREEMODEL_API_KEY` 存在 |
| A06 敏感数据泄露 | 日志含凭据 | 全局搜索 `logging.*request\|response\|header\|key` |
| A09 日志与监控不足 | 无审计日志 | 检查运行时是否记录操作流水 |

## 审查流程

```
1. 文件扫描 → 2. 凭据扫描 → 3. 路径分析 → 4. 日志审查 → 5. 依赖检查 → 6. 评分
```

按顺序执行，P0 阻断则停止并输出。

## 扫描命令参考

```bash
# 1. 硬编码密钥扫描
grep -rn "API_KEY\|SECRET\|password\|token\s*=" src/ runtime/ --include="*.py" | grep -v "test_" | grep -v "\.env"

# 2. .gitignore 检查
cat .gitignore | grep -q ".env" && echo "✅ .env 被忽略" || echo "❌ .env 未在 gitignore"

# 3. 路径穿越风险
grep -rn "open(" src/ runtime/ --include="*.py" | grep -v "with open" | grep -v "test_"

# 4. 日志泄露
grep -rn "logging\|print.*request\|print.*response\|print.*header\|print.*key" src/ runtime/

# 5. 依赖漏洞（需安装 pip-audit）
pip install pip-audit && pip-audit
```

## 输出格式

```markdown
## 安全审查结果：<通过|警告|失败>

### 严重问题（P0）
- [ ] <文件:行号> <描述> — 修复建议

### 警告（P1）
- [ ] <文件:行号> <描述> — 修复建议

### 改进建议（P2）
- [ ] <文件:行号> <描述> — 修复建议

### 总结
| 等级 | 计数 | 总体风险 |
|------|:----:|:--------:|
| P0   | 0    | 低       |
| P1   | 1    | 中       |
| P2   | 2    | 中       |

**总体风险等级：<低|中|高>**
**建议：** <简要总结>
```

## 跨 Skill 引用

| 引用目标 | 用途 |
|----------|------|
| [code-reviewer](../code-reviewer/SKILL.md) | 发现代码级问题时转交代码审查 |
| [project-conventions](../project-conventions/SKILL.md) | 检查 .env 配置、LLM 密钥管理约定 |
| [github-actions](../github-actions/SKILL.md) | CI 中集成安全扫描 Workflow |
