---
name: zh-encoding-safe
description: Handle Chinese text encoding safely in Windows, PowerShell, Python, Git, Markdown, YAML, JSON, logs, test output, and CLI automation. Use when Codex reads, edits, generates, validates, or debugs Chinese files or mojibake/garbled text such as 鍩轰簬, ä¸­æ–‡, question marks, broken console output, UTF-8 BOM issues, or encoding-sensitive scripts.
---

# Chinese Encoding Safety

Use this skill whenever Chinese text may be read from files, printed in terminals, passed through scripts, committed to Git, or compared in tests.

## Default Rules

- Prefer UTF-8 for all new text files.
- In PowerShell, read/write explicit encodings: `Get-Content -Encoding UTF8`, `Set-Content -Encoding UTF8`, `Out-File -Encoding UTF8`.
- In Python, pass `encoding="utf-8"` to `open()`, `Path.read_text()`, `Path.write_text()`, `json.load()`, and `json.dump()`.
- Do not trust terminal display alone. If Chinese looks garbled in console output, inspect the file bytes or read it with explicit UTF-8 before editing.
- Do not “fix” mojibake by blind search/replace. First identify whether the file bytes are correct and only the console display is wrong.
- Avoid embedding real secrets while testing encoding. Use harmless Chinese fixtures like `中文编码测试` and `测试用例通过`.

## Quick Workflow

1. Diagnose:
   - Run `python scripts/check_encoding.py <file-or-dir>` from this skill for suspected files.
   - Check whether the file has UTF-8 BOM, replacement characters, or common mojibake markers.
2. Read safely:
   - Prefer `Get-Content -Raw -Encoding UTF8 <path>` in PowerShell.
   - For command output that shows mojibake, rerun with Python reading bytes and decoding UTF-8.
3. Edit safely:
   - Use `apply_patch` for code edits.
   - Keep existing file style unless the task is explicitly to normalize encoding.
   - For generated artifacts, write UTF-8 and preserve Chinese text in source form.
4. Validate:
   - Run project tests that compare Chinese strings.
   - Run `git diff --check`.
   - Reopen modified files with explicit UTF-8 if the task depends on Chinese text.

## PowerShell Notes

- Windows PowerShell 5.1 and PowerShell 7 differ in default text encoding behavior.
- For reliable Chinese output, set console/session encoding when needed:

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
```

- Prefer explicit command flags over relying on session defaults.
- When a command prints garbled Chinese but tests pass, avoid rewriting files until file bytes are checked.

## Python Notes

Use this pattern for scripts that read/write Chinese:

```python
from pathlib import Path

text = Path("input.md").read_text(encoding="utf-8")
Path("output.md").write_text(text, encoding="utf-8", newline="\n")
```

For subprocesses that emit Chinese:

```python
import subprocess

result = subprocess.run(
    ["git", "status", "--short"],
    text=True,
    encoding="utf-8",
    errors="replace",
    capture_output=True,
    check=False,
)
```

## When Files Already Look Garbled

- If text resembles `鍩轰簬`, it is often UTF-8 bytes decoded as GBK/CP936.
- If text resembles `ä¸­æ–‡`, it is often UTF-8 bytes decoded as Latin-1/Windows-1252.
- If text contains `�`, data may already have replacement characters; recover from source history or original input if possible.
- If only terminal output is garbled, do not change the file.

## References

- Read `references/windows-python.md` when debugging PowerShell, Git, pytest, or Python subprocess encoding.
- Use `scripts/check_encoding.py` for a quick local scan.
