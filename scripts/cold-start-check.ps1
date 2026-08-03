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
    $keyEnvironment = $env:AGENTIC_QA_MODEL_API_KEY_ENV
    if ([string]::IsNullOrWhiteSpace($keyEnvironment)) {
        if (-not [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
            $keyEnvironment = "DEEPSEEK_API_KEY"
        } elseif (-not [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
            $keyEnvironment = "OPENAI_API_KEY"
        }
    }
    if ([string]::IsNullOrWhiteSpace($keyEnvironment)) {
        throw "No model API key environment variable is selected or configured"
    }
    $keyValue = [Environment]::GetEnvironmentVariable($keyEnvironment)
    if ([string]::IsNullOrWhiteSpace($keyValue)) {
        throw "Model API key environment variable is empty: $keyEnvironment"
    }
    if ([string]::IsNullOrWhiteSpace($env:PG_LOCAL_PASSWORD)) {
        throw "PostgreSQL password environment variable is empty: PG_LOCAL_PASSWORD"
    }
    Invoke-CheckedPython -Arguments @(
        "-c",
        "from harness.infrastructure.persistence.postgres_checkpoint import CheckpointPostgresConfig; import psycopg; connection = psycopg.connect(**CheckpointPostgresConfig().connection_kwargs()); connection.close(); print('PostgreSQL: reachable')"
    )
    Write-Output "model key: configured via $keyEnvironment"
}

if ($Full) {
    Invoke-CheckedPython -Arguments @("-m", "ruff", "check", ".")
    Invoke-CheckedPython -Arguments @("-m", "pytest", "-q")
    Invoke-CheckedPython -Arguments @("-m", "harness", "eval", "run")
    Invoke-CheckedPython -Arguments @("-m", "mkdocs", "build", "--strict")
    Invoke-CheckedPython -Arguments @("-m", "build", "--wheel")
}

Write-Output "cold-start check: passed"
