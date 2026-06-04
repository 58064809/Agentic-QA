# prototype-notes 输入已废弃

> 状态：deprecated
> 用途：保留路径只用于历史任务引用和文档一致性检查，不作为 Runtime 输入模板使用。

当前 Runtime 明确不分析图片/原型图内容，不读取 `prototype-notes.md`，也不接视觉模型。需求分析和测试用例生成只基于 `input/requirement.md` 与可选 `input/api.md` 的文本内容。

如果 `input/requirement.md` 中出现图片/原型图引用，Runtime 只记录 warning，并提示人工确认图片中是否存在未写入正文的字段、按钮、状态、弹窗、权限差异或交互规则。不得基于图片内容编造字段、按钮、页面布局或交互。
