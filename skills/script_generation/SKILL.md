# Script Generation Skill

输入：
- 用户请求
- 需求文档

处理原则：
- 默认生成 pytest Python 骨架。
- 用户明确提到 API/接口时，生成 pytest API 自动化骨架。
- 用户明确提到 Playwright/E2E/页面自动化时，生成 Playwright TypeScript 骨架。
- 未绑定真实页面/API/DB 动作时，不允许假通过；用 NotImplementedError 或 test.skip 标识待绑定。

输出：
- pytest / API pytest / Playwright 脚本骨架
- 推荐文件名
- 基于的需求项
