# Runs every check available on this machine. Exit code != 0 on failure.
#   powershell -ExecutionPolicy Bypass -File scripts\validate.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$failed = @()

function Step($name, [scriptblock]$cmd) {
    Write-Host "`n== $name" -ForegroundColor Cyan
    & $cmd
    if ($LASTEXITCODE -ne 0) { $script:failed += $name }
}

# DB-backed tests need PostgreSQL. Start the compose db (if Docker exists) and default the test URL;
# the test suite creates the harvestique_test database itself if it is missing.
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Push-Location $root
    docker compose up -d --wait db
    Pop-Location
}
# the host port comes from .env (POSTGRES_HOST_PORT), the same value docker compose uses
$dbPort = "5433"
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    $line = Select-String -Path $envFile -Pattern '^\s*POSTGRES_HOST_PORT\s*=\s*(\d+)' | Select-Object -First 1
    if ($line) { $dbPort = $line.Matches[0].Groups[1].Value }
}
if (-not $env:TEST_DATABASE_URL) {
    $env:TEST_DATABASE_URL = "postgresql+psycopg://harvestique:harvestique@localhost:$dbPort/harvestique_test"
}
Write-Host "TEST_DATABASE_URL=$env:TEST_DATABASE_URL"

Set-Location (Join-Path $root "backend")
$py = ".\.venv\Scripts"
if (Test-Path "$py\python.exe") {
    Step "ruff lint"      { & "$py\ruff.exe" check . }
    Step "ruff format"    { & "$py\ruff.exe" format --check . }
    Step "mypy"           { & "$py\mypy.exe" app }
    Step "pytest"         { & "$py\python.exe" -m pytest }
    Step "alembic drift"  {
        $env:DATABASE_URL = $env:TEST_DATABASE_URL
        & "$py\alembic.exe" upgrade head
        if ($LASTEXITCODE -eq 0) { & "$py\alembic.exe" check }
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    }
} elseif (Get-Command docker -ErrorAction SilentlyContinue) {
    # no local virtual environment: run the same backend checks inside Docker (migrations are covered by the tests)
    Step "backend (docker)" { & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "test-backend.ps1") }
} else {
    Write-Host "No backend\.venv and no Docker - skipping backend checks" -ForegroundColor Yellow
    $script:failed += "backend (not run)"
}

Set-Location $root
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Step "compose config" { docker compose config --quiet }
} else { Write-Host "docker not found - skipping compose validation" -ForegroundColor Yellow }

if (Get-Command flutter -ErrorAction SilentlyContinue) {
    Set-Location (Join-Path $root "frontend")
    Step "flutter analyze" { flutter analyze }
    Step "flutter test"    { flutter test }
} else { Write-Host "flutter not found - skipping frontend checks" -ForegroundColor Yellow }

if ($failed.Count -gt 0) { Write-Host "`nFAILED: $($failed -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host "`nAll checks passed." -ForegroundColor Green
