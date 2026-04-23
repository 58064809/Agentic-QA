# 需求工作区

每个新需求放一个独立目录，避免 PRD、原型、日志、脚本和输出互相污染。

推荐结构：

```text
requirements/
  deposit-management/
    docs/
    prototype/
    logs/
    tests/
    outputs/
```

使用方式：
- PRD、需求说明放 `docs/`
- 原型、截图、设计稿放 `prototype/`
- 需求相关日志放 `logs/`
- 需求相关 pytest 脚本放 `tests/`
- 助手分析、用例、脚本草稿默认保存到 `outputs/`
