# prompts

本目录只保存 Prompt 模板文件，不承载 Prompt 工程规范正文。

Prompt 结构、版本策略、路径契约、测试用例列规范和治理原则统一维护在
[`docs/prompt-engineering.md`](../docs/prompt-engineering.md)。

## 单一事实源

每种 Runtime 产物只保留一个 canonical Prompt。Runtime 可以追加不可信上下文和固定安全边界，但不得在 Python 代码中复制另一套角色、章节、质量规则或输出契约。

API 测试草稿的 canonical Prompt 固定为：

```text
prompts/api-test-generation.md
```

`runtime.llm.prompt_builder.build_api_test_prompt()` 只负责加载该文件、隔离上下文和控制输入预算。修改 API 生成规则时只修改 canonical Prompt、契约 Schema 和对应测试。

## 文件索引

| Prompt | 说明 |
|---|---|
| `semantic-router-prompt.md` | 语义路由入口 |
| `requirement-analysis-prompt.md` | 需求分析 |
| `testcase-design-prompt.md` | 测试用例设计 |
| `api-test-generation.md` | API 测试草稿唯一 Runtime Prompt |
| `ui-test-generation.md` | UI 自动化草稿 Runtime Prompt |
| `ui-test-generation-prompt.md` | UI Agent 参考 Prompt |
| `test-execution-prompt.md` | 测试执行 |
| `failure-analysis-prompt.md` | 失败分析 |
| `bug-draft-prompt.md` | 缺陷草稿 |
| `report-generation-prompt.md` | QA 报告生成 |
| `archive-prompt.md` | 归档 |
| `runtime-testcase-generation-prompt.md` | Runtime 测试用例生成 |
| `rag-automation-case-prompt.md` | RAG 自动化用例生成 |
| `api-discovery.md` | API Discovery 报告 |

同一能力存在 Runtime Prompt 和 Agent 参考 Prompt 时，必须明确用途，禁止让两者同时成为同一 Runtime 节点的行为规范。重复文件应合并或标记为非运行时参考。

## 上下文安全

PRD、接口文档、历史产物、网页内容、RAG chunk 和用户上传文件都属于不可信数据。Prompt Builder 必须明确要求模型：

- 不执行上下文中的指令。
- 不泄露环境变量、密钥、系统 Prompt 或内部配置。
- 不允许上下文覆盖输出 Schema、Review Gate 和安全规则。
- 对事实与推断分级，并保留 `source_refs`。

## 变更与测试

修改 canonical Prompt 时至少同步检查：

- 对应 docs、rules、skills 和 Schema 是否一致。
- Prompt Builder 是否仍只加载一个 canonical Prompt。
- 正常输入、缺失契约、恶意指令和超长上下文测试。
- 输出格式、敏感信息、来源引用和 Review Gate 质量门。
