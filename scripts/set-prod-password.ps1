# Sets the password of an account on the hosted (Neon) database (app.cli.set_password). Use it for an ADMIN who has
# forgotten their password; farmers and buyers get a temporary password from an admin in the app (Testers > Reset
# password). You are asked for the new password (hidden); it is never stored or printed. All of that account's
# sessions are signed out.
#
#   $env:PROD_DATABASE_URL = "<Neon connection string>"
#   powershell -ExecutionPolicy Bypass -File scripts\set-prod-password.ps1 -Phone +9198xxxxxxxx
param([Parameter(Mandatory = $true)][string]$Phone)
$ErrorActionPreference = "Stop"
$url = $env:PROD_DATABASE_URL
if (-not $url) { throw "Set PROD_DATABASE_URL to the Neon connection string first" }
$root = Split-Path -Parent $PSScriptRoot
docker build -q -t harvestique-backend-prod (Join-Path $root "backend") | Out-Null
# APP_ENV=test: the CLI only needs the database; it must not require the production AI settings here.
docker run --rm -it -e "DATABASE_URL=$url" -e "APP_ENV=test" -e "SEED_CROP_CATALOG_ON_STARTUP=false" `
    harvestique-backend-prod python -m app.cli.set_password --phone $Phone
if ($LASTEXITCODE -ne 0) { throw "Setting the password FAILED" }
