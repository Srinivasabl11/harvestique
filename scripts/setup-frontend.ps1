# Generates Android platform files (keeps existing lib/ and test/) and fetches packages.
#   powershell -ExecutionPolicy Bypass -File scripts\setup-frontend.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "frontend")

flutter create . --platforms=android --org com.harvestique --project-name harvestique
if (Test-Path "test\widget_test.dart") { Remove-Item "test\widget_test.dart" }  # template counter test
flutter pub get
Write-Host "Frontend ready. Next: flutter analyze; flutter test" -ForegroundColor Green
