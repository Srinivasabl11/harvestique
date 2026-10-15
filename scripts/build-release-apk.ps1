# Builds the shareable release APK that talks to the hosted Harvestique server (frontend/config/production.json).
# Refuses a localhost / LAN / plain-HTTP server address, checks the server answers, runs the Flutter tests, then builds.
#
#   powershell -ExecutionPolicy Bypass -File scripts\build-release-apk.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\build-release-apk.ps1 -SkipTests
#
# Needs frontend/android/key.properties + the keystore it names (see docs/DEPLOYMENT.md); without them the APK would be
# signed with this PC's debug key, which other PCs cannot reproduce, so the script stops.
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
$config = Join-Path $frontend "config\production.json"

$url = (Get-Content $config -Raw | ConvertFrom-Json).API_BASE_URL
$hostName = ([Uri]$url).Host
if (-not $url.StartsWith("https://") -or $hostName -match '^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)') {
    throw "API_BASE_URL in $config must be the public HTTPS server, not '$url'"
}
if (-not (Test-Path (Join-Path $frontend "android\key.properties"))) {
    throw "frontend\android\key.properties is missing: restore it from your backup (docs/DEPLOYMENT.md, 'Signing key')"
}

Write-Host "Checking $url/health/ready (a sleeping free server can take about a minute to wake) ..."
$ready = Invoke-RestMethod -Uri "$url/health/ready" -TimeoutSec 120
# 'degraded' = database fine, an optional AI service (assistant model or photo model) is down: the app works and says
# so on the AI screens, so the APK can still be built.
if ($ready.status -notin @("ready", "degraded")) { throw "The server is not ready: $($ready | ConvertTo-Json -Compress)" }
if ($ready.status -eq "degraded") { Write-Warning "Server is up but an AI service is unavailable: $($ready.components | ConvertTo-Json -Compress)" }

Push-Location $frontend
try {
    flutter pub get
    if ($LASTEXITCODE -ne 0) { throw "flutter pub get failed" }
    if (-not $SkipTests) {
        flutter test
        if ($LASTEXITCODE -ne 0) { throw "Flutter tests failed; no APK was built" }
    }
    flutter build apk --release --dart-define-from-file=config/production.json
    if ($LASTEXITCODE -ne 0) { throw "flutter build apk failed" }
} finally {
    Pop-Location
}

$apk = Join-Path $frontend "build\app\outputs\flutter-apk\app-release.apk"
$item = Get-Item $apk
$hash = (Get-FileHash $apk -Algorithm SHA256).Hash
Write-Host "`nRelease APK: $($item.FullName)" -ForegroundColor Green
Write-Host ("Size: {0:N1} MB ({1} bytes)  SHA-256: {2}" -f ($item.Length / 1MB), $item.Length, $hash)
Write-Host "Server: $url"
