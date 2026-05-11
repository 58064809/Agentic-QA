# 任务 013：接入 MarkItDown，实现需求文档自动转 Markdown 后再分析

## 任务目标

真实产品需求可能是 Word、PDF、TXT 或 Markdown。当前 Runtime 主要读取 `prd/<需求名>/requirement.md`，这会导致用户拿到 Word/PDF 需求时必须手工转换。

本任务目标：接入 Microsoft MarkItDown，把“需求文档格式检查与 Markdown 归一化”作为需求分析前置能力。

最终效果：

```text
用户说：帮我分析 XXX 需求
  ↓
Runtime / Codex 定位 prd/<XXX>/ 下的需求源文件
  ↓
如果已有 requirement.md：直接进入需求分析
  ↓
如果没有 requirement.md，但存在 requirement.docx / requirement.pdf / requirement.txt / requirement.html 等：先用 MarkItDown 转成 requirement.md
  ↓
再执行 analyze / mvp 需求分析链路
```

本任务必须保证：Markdown 正常跑；非 Markdown 先转 Markdown 再跑。

## 硬性要求

1. 直接在 `master` 修改，不创建新分支。
2. 文档尽量使用中文。
3. 不提交真实业务 Word/PDF、`.venv/`、`.env`、`.runtime/runs/`。
4. 不开放通用 shell。
5. 不开放任意 filesystem write。
6. 不做目录递归扫描或批量转换；只处理目标 PRD 工作区内明确命名的需求源文件。
7. 不接数据库、向量库、Web UI 或复杂 RAG。
8. 不把当前公司的具体业务规则写入通用代码。
9. 转换结果必须写入目标 PRD 工作区内的 `requirement.md`。
10. 如果 `requirement.md` 已存在，默认不覆盖，直接使用现有 Markdown。
11. 如果源文档和 `requirement.md` 都不存在，必须给出清晰错误。
12. 完成后必须按 `rules/codex-output-rules.md` 的标准完成回执模板回复。

## 背景依据

请先读取：

```text
README.md
AGENTS.md
pyproject.toml
runtime/README.md
runtime/graph/nodes/mvp_context_loader.py
runtime/graph/mvp_graph.py
```

注意：本仓库当前 Runtime MVP 已支持：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/<需求名>
python -m runtime.cli generate-testcases "帮我生成测试用例" --prd prd/<需求名>
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/<需求名>
```

本任务要把文档归一化接入 `analyze` 和 `mvp` 的前置上下文加载流程。`generate-testcases` 如果没有 `requirement.md`，也应该尝试归一化后再生成用例。

## 依赖安装要求

请先在本地虚拟环境中验证安装：

```bash
pip install "markitdown[all]"
```

如果当前环境或版本不支持 extras，再退回：

```bash
pip install markitdown
```

验证成功后更新 `pyproject.toml`。

建议优先加入：

```toml
"markitdown[all]>=0.1",
```

如果 extras 在当前环境不可用，则加入：

```toml
"markitdown>=0.1",
```

以实际可安装、可测试为准。

## 支持的需求源文件约定

在每个 PRD 工作区内，优先识别以下文件名：

```text
requirement.md
requirement.docx
requirement.pdf
requirement.txt
requirement.html
requirement.htm
requirement.rtf
```

也允许补充识别：

```text
需求.md
需求.docx
需求.pdf
需求.txt
需求.html
需求.htm
```

识别优先级：

1. `requirement.md` 存在：直接使用，不转换。
2. `requirement.docx` 存在：转换为 `requirement.md`。
3. `requirement.pdf` 存在：转换为 `requirement.md`。
4. 其他受支持文本/HTML格式。
5. 如果多个非 Markdown 源同时存在，按固定优先级选择，并在 warnings 中说明。

## 推荐新增模块

新增：

```text
runtime/tools/document_converter.py
runtime/graph/nodes/requirement_normalizer.py
```

### document_converter.py

建议提供：

```python
convert_requirement_to_markdown(source_path: Path, output_path: Path, *, overwrite: bool = False) -> str
```

要求：

- 使用 MarkItDown 转换。
- 默认不覆盖已有 `requirement.md`。
- 返回转换后的 Markdown 文本或输出路径。
- 捕获 MarkItDown 异常并返回清晰错误。
- 不打印完整堆栈到 CLI。

### requirement_normalizer.py

建议提供：

```python
normalize_requirement_document(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState
```

职责：

1. 定位目标 PRD 工作区。
2. 如果 `requirement.md` 存在，记录 `requirement_source_type=markdown`，直接返回。
3. 如果不存在，查找受支持源文件。
4. 找到 Word/PDF 等源文件后，转换为 `requirement.md`。
5. 记录 warnings，例如：`已将 requirement.docx 转换为 requirement.md`。
6. 如果转换失败，写入 `state.errors`。

## Runtime 接入要求

将归一化节点接入以下流程的上下文加载前：

```text
analyze
mvp
generate-testcases
```

推荐流程：

```text
mvp_command_router_node
  ↓
mvp_workflow_selector_node
  ↓
requirement_normalizer_node
  ↓
mvp_context_loader_node
  ↓
后续分析/用例生成节点
```

要求：

- `requirement.md` 已存在时，不调用 MarkItDown。
- 非 Markdown 转换成功后，后续 context loader 应正常读取新生成的 `requirement.md`。
- 转换写入 `requirement.md` 属于受控写入，允许在 normalizer 节点执行，不受 `--approve-write` 限制；因为这是输入归一化，不是 QA 产物生成。
- 但不得覆盖已有 `requirement.md`。

## CLI 行为要求

现有命令无需变更即可生效：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/<需求名> --use-llm
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/<需求名> --use-llm
```

可选新增显式命令：

```bash
python -m runtime.cli normalize-requirement --prd prd/<需求名>
```

如果新增该命令，必须支持：

- 已有 `requirement.md`：提示无需转换。
- 存在 `requirement.docx` / `requirement.pdf`：转换为 `requirement.md`。
- 无任何需求源文件：返回清晰错误。

## Run Records 扩展要求

运行记录中建议增加：

```json
"requirement_normalization": {
  "performed": true,
  "source_path": "prd/<id>/requirement.docx",
  "output_path": "prd/<id>/requirement.md",
  "source_type": "docx",
  "skipped_reason": null
}
```

如果 `requirement.md` 已存在：

```json
"requirement_normalization": {
  "performed": false,
  "source_path": "prd/<id>/requirement.md",
  "output_path": "prd/<id>/requirement.md",
  "source_type": "markdown",
  "skipped_reason": "requirement.md already exists"
}
```

不得把 Word/PDF 原文完整写入运行记录。

## 文档更新要求

更新：

```text
README.md
runtime/README.md
docs/architecture/production-agent-runtime-roadmap.md
```

说明：

1. Runtime 支持 Word/PDF/TXT/HTML 需求文档转 Markdown。
2. 推荐把原始需求放到 `prd/<id>/requirement.docx` 或 `prd/<id>/requirement.pdf`。
3. 如果已有 `requirement.md`，直接使用，不转换。
4. 转换输出为 `prd/<id>/requirement.md`。
5. 转换后再执行需求分析和测试用例生成。

## 测试要求

新增或更新测试：

```text
tests/unit/test_requirement_normalizer.py
tests/unit/test_markitdown_converter.py
```

至少覆盖：

1. 已有 `requirement.md` 时不转换。
2. 只有 `requirement.txt` 时转换为 `requirement.md`。
3. `requirement.md` 已存在时不覆盖。
4. 没有任何需求源文件时返回错误。
5. 多个源文件存在时按优先级选择并给 warning。
6. normalize 后 analyze 流程可以继续读取 `requirement.md`。
7. MarkItDown 调用失败时返回清晰错误。

测试中可以优先使用 `.txt` 样例，避免引入真实 Word/PDF 文件。Word/PDF 能力通过 MarkItDown 依赖和转换器接口覆盖即可。

## .gitignore 要求

确认仍然忽略：

```gitignore
.venv/
.runtime/runs/
.env
.env.*
```

不要提交真实业务文档。如果新增样例，只允许使用虚构内容，例如：

```text
prd/sample-doc-requirement/requirement.txt
```

## 验收命令

完成后尽量执行：

```bash
pip install -e .
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-login-requirement --no-record-run
python -m runtime.cli mvp "帮我分析需求并生成测试用例" --prd prd/sample-login-requirement --no-record-run
python scripts/validate_docs_consistency.py
python scripts/validate_prd_workspace.py prd/sample-login-requirement
pytest
ruff check .
```

如果新增 txt 样例 PRD，请额外验证：

```bash
python -m runtime.cli analyze "帮我分析这个需求" --prd prd/sample-doc-requirement --no-record-run
```

如果本地有 Word/PDF 样例，可手工验证，但不要提交真实文件。

## 不做事项

本任务不要做：

1. 不做批量文档导入平台。
2. 不做 OCR 平台。
3. 不接向量库。
4. 不做 Web UI。
5. 不把转换后的真实业务需求提交到仓库。
6. 不覆盖已有 `requirement.md`。
7. 不跳过 012B 的评审级质量修复。

## 与 012B 的关系

012B 修复“输出是否达到领导评审级”。

013 修复“输入文档是否能自动归一化为 Markdown”。

建议执行顺序：

```text
先执行 012B
再执行 013
```

如果时间紧，也可以先执行 013，但最终周一真实需求前必须同时完成 012B 和 013。

## 完成回执要求

完成后必须说明：

1. 是否已安装并接入 MarkItDown。
2. `pyproject.toml` 加入的是 `markitdown[all]` 还是 `markitdown`。
3. `requirement.md` 已存在时是否跳过转换。
4. Word/PDF/TXT 转 Markdown 的入口是什么。
5. analyze/mvp 是否已自动前置归一化。
6. 是否不覆盖已有 `requirement.md`。
7. 是否执行 pytest 和 ruff。
8. 周一真实需求应该如何放文件和执行命令。
