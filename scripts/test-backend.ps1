# Runs the backend checks (ruff lint, ruff format, mypy, pytest) inside Docker. No Python install on Windows is
# needed, and no AI tool. The tests use their own database (harvestique_test); the live data is never touched.
#
#   powershell -ExecutionPolicy Bypass -File scripts\test-backend.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\test-backend.ps1 -Pytest "tests/unit -q"   # a subset
#
param([string]$Pytest = "-q")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    docker compose up -d --wait db
    # the runner image builds on the backend image; build that first if it does not exist yet
    docker image inspect harvestique-backend *> $null
    if ($LASTEXITCODE -ne 0) { docker compose build backend }
    docker build -q -f backend/Dockerfile.test -t hq-test-runner backend | Out-Null
    $network = (docker inspect harvestique-db-1 --format "{{range `$k, `$v := .NetworkSettings.Networks}}{{`$k}}{{end}}").Trim()
    $commands = "cp -r /src /tmp/w && cd /tmp/w/backend && export PATH=`$PATH:/home/appuser/.local/bin && " +
        "echo '== ruff lint' && ruff check app tests && " +
        "echo '== ruff format' && ruff format --check app tests && " +
        "echo '== mypy' && mypy app && " +
        "echo '== pytest' && python -m pytest -p no:cacheprovider $Pytest"
    docker run --rm --network $network `
        -v "${root}\backend:/src/backend:ro" -v "${root}\docs:/src/docs:ro" `
        -e "TEST_DATABASE_URL=postgresql+psycopg://harvestique:harvestique@db:5432/harvestique_test" `
        --entrypoint sh hq-test-runner -c $commands
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($code -eq 0) { Write-Host "`nAll backend checks passed." -ForegroundColor Green }
else { Write-Host "`nBackend checks FAILED (exit $code)." -ForegroundColor Red }
exit $code
