param(
    [switch]$Full,
    [switch]$Runtime
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "Missing .venv. Run: python -m venv .venv"
}

function Invoke-CheckedPython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $venvPython @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

Set-Location $repoRoot
Invoke-CheckedPython -Arguments @(
    "-c",
    "import sys; assert sys.version_info >= (3, 10), sys.version; print(sys.version.split()[0])"
)
Invoke-CheckedPython -Arguments @("-m", "pip", "check")
Invoke-CheckedPython -Arguments @(
    "-c",
    "import build, harness, mkdocs, pytest, ruff; print('required imports: ok')"
)
Invoke-CheckedPython -Arguments @("-m", "harness", "--help")

if ($Runtime) {
    Invoke-CheckedPython -Arguments @("-m", "harness", "config", "doctor")
    Invoke-CheckedPython -Arguments @(
        "-c",
        "from harness.infrastructure.local_config import FilesystemLocalConfigLoader; from harness.infrastructure.persistence.postgres_checkpoint import CheckpointPostgresConfig; import psycopg; local = FilesystemLocalConfigLoader('.').load_required(); value = local.postgres; config = CheckpointPostgresConfig(host=value.host, port=value.port, database=value.database, user=value.user, password=value.password, connect_timeout_seconds=value.connect_timeout_seconds); connection = psycopg.connect(**config.connection_kwargs()); connection.close(); print('PostgreSQL: reachable'); print('model key: configured via ' + local.model.api_key_env)"
    )
}

if ($Full) {
    Invoke-CheckedPython -Arguments @("-m", "ruff", "check", ".")
    Invoke-CheckedPython -Arguments @("-m", "pytest", "-q")
    Invoke-CheckedPython -Arguments @("-m", "harness", "eval", "run")
    Invoke-CheckedPython -Arguments @("-m", "mkdocs", "build", "--strict")
    Invoke-CheckedPython -Arguments @("-m", "build", "--wheel")
}

Write-Output "cold-start check: passed"
