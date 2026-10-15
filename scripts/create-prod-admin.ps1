# Creates the admin account on the hosted (Neon) database, the same way as locally (app.cli.create_admin). Admins
# cannot be created through the public API. You are asked for the password (hidden); it is never stored or printed.
# Sign in with this phone number in the app: the admin screens include "Testers" (approve / suspend / revoke).
#
#   $env:PROD_DATABASE_URL = "<Neon connection string>"
#   powershell -ExecutionPolicy Bypass -File scripts\create-prod-admin.ps1 -Phone +9198xxxxxxxx -Name "Your Name"
param([Parameter(Mandatory = $true)][string]$Phone, [Parameter(Mandatory = $true)][string]$Name)
$ErrorActionPreference = "Stop"
$url = $env:PROD_DATABASE_URL
if (-not $url) { throw "Set PROD_DATABASE_URL to the Neon connection string first" }
$root = Split-Path -Parent $PSScriptRoot
docker build -q -t harvestique-backend-prod (Join-Path $root "backend") | Out-Null
# APP_ENV=test: the CLI only needs the database; it must not require the production SMS/AI settings here.
docker run --rm -it -e "DATABASE_URL=$url" -e "APP_ENV=test" -e "SEED_CROP_CATALOG_ON_STARTUP=false" `
    harvestique-backend-prod python -m app.cli.create_admin --phone $Phone --name $Name
if ($LASTEXITCODE -ne 0) { throw "Creating the admin FAILED" }
