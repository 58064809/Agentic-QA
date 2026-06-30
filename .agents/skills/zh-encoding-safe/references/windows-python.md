# Windows, PowerShell, and Python Encoding Notes

## Reliable PowerShell Patterns

Use explicit encoding when Chinese text matters:

```powershell
Get-Content -Raw -Encoding UTF8 path\to\file.md
Set-Content -Encoding UTF8 path\to\file.md -Value $text
Out-File -Encoding UTF8 path\to\log.txt
```

For the current process:

```powershell
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
```

PowerShell 7 generally defaults to UTF-8 without BOM for text output. Windows PowerShell 5.1 has more legacy behavior, so explicit `-Encoding UTF8` is safer.

## Reliable Python Patterns

Use explicit encoding:

```python
Path(path).read_text(encoding="utf-8")
Path(path).write_text(content, encoding="utf-8", newline="\n")
json.loads(text)
json.dumps(data, ensure_ascii=False)
```

When running subprocesses:

```python
subprocess.run(args, text=True, encoding="utf-8", errors="replace")
```

If Python defaults are suspect, use one of:

```powershell
$env:PYTHONUTF8 = "1"
python -X utf8 script.py
```

## Git and Tests

- Prefer assertions against actual Unicode strings, not mojibake.
- If `pytest` output is garbled but assertions pass, inspect source files with explicit UTF-8 before changing code.
- Run `git diff --check` before commit.
- Keep `.md`, `.yml`, `.json`, `.py`, and test fixtures as UTF-8 unless the repo explicitly requires another encoding.
