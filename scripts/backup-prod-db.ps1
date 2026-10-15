# Backs up the hosted (Neon) production database to a custom-format dump OUTSIDE the repository. Read-only: it never
# changes the database. Run it before every deployment that adds a migration, and regularly (e.g. weekly).
#
#   $env:PROD_DATABASE_URL = "postgresql://user:password@ep-xxx.ap-southeast-1.aws.neon.tech/harvestique?sslmode=require"
#   powershell -ExecutionPolicy Bypass -File scripts\backup-prod-db.ps1
#
# The connection string is read from the environment so it is never written to a file in the repo.
# Restore (into an EMPTY database only): docs/DEPLOYMENT.md, "Restore a backup".
param([string]$OutDir = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "harvestique-backups"))
$ErrorActionPreference = "Stop"
$url = $env:PROD_DATABASE_URL
if (-not $url) { throw "Set PROD_DATABASE_URL to the Neon connection string first (Neon console > Connect)" }
$url = $url -replace '^postgresql\+psycopg://', 'postgresql://'

New-Item -ItemType Directory -Force $OutDir | Out-Null
$name = "harvestique_prod_{0}.dump" -f (Get-Date -Format "yyyyMMdd_HHmmss")
# pg_dump must be at least the server's major version (Neon: 18), so it runs from the postgres:18 image.
docker run --rm -e "DBURL=$url" -v "${OutDir}:/out" postgres:18-alpine `
    sh -c "pg_dump `"`$DBURL`" -Fc --no-owner --no-acl -f /out/$name && pg_restore -l /out/$name | grep -c 'TABLE DATA'"
if ($LASTEXITCODE -ne 0) { throw "Backup FAILED" }
$item = Get-Item (Join-Path $OutDir $name)
Write-Host ("Backup written: {0} ({1:N0} KB)" -f $item.FullName, ($item.Length / 1KB)) -ForegroundColor Green
