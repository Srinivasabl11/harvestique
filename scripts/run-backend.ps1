# Starts PostgreSQL in Docker, applies migrations, runs the API with auto-reload on the host.
#   powershell -ExecutionPolicy Bypass -File scripts\run-backend.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
docker compose up -d db

Set-Location (Join-Path $root "backend")
# Settings read the repo-root .env automatically (see app/core/config.py).
& .\.venv\Scripts\alembic.exe upgrade head
& .\.venv\Scripts\uvicorn.exe app.main:create_app --factory --reload --host 0.0.0.0 --port 8000
