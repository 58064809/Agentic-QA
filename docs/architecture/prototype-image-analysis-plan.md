# 原型图识别后续方案

## 当前阶段

当前 Runtime MVP 只走文本链路，不上传、不解析、不直接分析图片二进制。原型图中的页面结构、字段规则、按钮行为、弹窗、状态、权限差异和错误文案，需要先由人工整理到 `prototype-notes.md`。

推荐的当前输入链路：

```text
Word/PDF/TXT/HTML -> MarkItDown -> requirement.md
人工阅读原型图 -> prototype-notes.md
api-doc.md（可选）
requirement.md + prototype-notes.md + api-doc.md -> 需求分析 -> 测试用例
```

如果 `requirement.md` 中存在 Markdown 图片引用但缺少 `prototype-notes.md`，Runtime 只能基于文本生成草稿，并在 warning 和待确认问题中提示原型信息不足。

## 后续阶段

后续如要接入视觉模型，建议拆成独立、可审计的输入归一化流程：

1. 从 Word/PDF 或人工上传目录中提取原型图片，统一保存到 `assets/prototypes/`。
2. 由视觉模型读取图片并生成 `prototype-analysis.md`，内容包括页面清单、字段、按钮、跳转、状态、弹窗、错误文案和权限差异。
3. 人工审核并修订 `prototype-analysis.md`，必要时同步整理为 `prototype-notes.md`。
4. 最终分析链路同时读取 `requirement.md`、`prototype-notes.md`、`prototype-analysis.md` 和 `api-doc.md`。

## 边界

- 视觉识别结果必须是可 diff、可人工审核的 Markdown，不直接把图片理解结果隐藏在运行时状态里。
- 视觉模型接入不能替代 `requirement.md`，也不能绕过 Human Review Gate。
- 图片、业务原型和真实需求源文件可能包含敏感信息，不应默认提交到 Git。
- 未经人工确认的视觉识别结果只能作为待审核输入，不应直接定性为最终需求结论。
