# One-time copy of a backup (e.g. the local data) into a NEW, EMPTY hosted database. It refuses to run when the target
# already has any table, so it can never overwrite or merge into production data.
#
#   $env:TARGET_DATABASE_URL = "postgresql://user:password@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
#   powershell -ExecutionPolicy Bypass -File scripts\restore-to-empty-db.ps1 -Dump ..\harvestique-backups\harvestique_local_20261015_082115.dump
param([Parameter(Mandatory = $true)][string]$Dump)
$ErrorActionPreference = "Stop"
$url = $env:TARGET_DATABASE_URL
if (-not $url) { throw "Set TARGET_DATABASE_URL to the empty database's connection string first" }
$url = $url -replace '^postgresql\+psycopg://', 'postgresql://'
$file = Get-Item $Dump
$dir = $file.DirectoryName

$tables = docker run --rm -e "DBURL=$url" postgres:18-alpine `
    psql "$url" -Atc "select count(*) from information_schema.tables where table_schema = 'public'"
if ($LASTEXITCODE -ne 0) { throw "Could not connect to the target database" }
if ([int]$tables.Trim() -ne 0) { throw "The target database already has $($tables.Trim()) tables: refusing to restore over it" }

docker run --rm -e "DBURL=$url" -v "${dir}:/in:ro" postgres:18-alpine `
    sh -c "pg_restore --no-owner --no-acl --exit-on-error -d `"`$DBURL`" /in/$($file.Name) && psql `"`$DBURL`" -Atc 'select version_num from alembic_version; select count(*) as users from users'"
if ($LASTEXITCODE -ne 0) { throw "Restore FAILED (the target may be partly filled; inspect it before retrying)" }
Write-Host "Restored $($file.Name) into the empty target database." -ForegroundColor Green
