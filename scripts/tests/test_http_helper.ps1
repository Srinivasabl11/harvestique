# Tests for scripts\lib\http.ps1 (Invoke-Http), the helper verify-production.ps1 uses, against a local mock server.
# Run on Windows PowerShell 5.1 (the case that failed) and, if installed, PowerShell 7:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\test_http_helper.ps1
#
# Needs Python 3 on PATH (standard library only). Exit code 0 = all passed.
$ErrorActionPreference = "Stop"
. (Join-Path (Split-Path -Parent $PSScriptRoot) "lib\http.ps1")

$failed = 0
function Assert([string]$name, [bool]$ok, [string]$detail = "") {
    if ($ok) { Write-Host "PASS  $name" -ForegroundColor Green }
    else { Write-Host "FAIL  $name  $detail" -ForegroundColor Red; $script:failed++ }
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "python"
$psi.Arguments = "-I `"$(Join-Path $PSScriptRoot 'mock_http_server.py')`""
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.CreateNoWindow = $true
$server = [System.Diagnostics.Process]::Start($psi)
try {
    $port = [int]$server.StandardOutput.ReadLine()
    $base = "http://127.0.0.1:$port"
    Write-Host "PowerShell $($PSVersionTable.PSVersion), mock server on port $port"

    $r = Invoke-Http -Method GET -Uri "$base/ok"
    Assert "200 status and body" ($r.Status -eq 200 -and $r.Body -match '"status": "ok"') "$($r.Status) $($r.Body)"

    $r = Invoke-Http -Method POST -Uri "$base/auth/login" -Json '{"phone":"+919000000099","password":"x"}'
    Assert "401 keeps its status" ($r.Status -eq 401) "$($r.Status)"
    Assert "401 body is readable (invalid_credentials)" ($r.Body -match "invalid_credentials") "body: '$($r.Body)'"

    $r = Invoke-Http -Method GET -Uri "$base/boom"
    Assert "500 status and error body" ($r.Status -eq 500 -and $r.Body -match "internal_error") "$($r.Status) $($r.Body)"

    $r = Invoke-Http -Method GET -Uri "$base/redirect" -NoRedirect
    Assert "301 is returned, not status 0" ($r.Status -eq 301) "$($r.Status)"
    Assert "301 Location header is readable" ([string]$r.Headers["Location"] -eq "https://example.test/redirect") "'$($r.Headers["Location"])'"

    $r = Invoke-Http -Method POST -Uri "$base/echo" -Json '{"a":1,"phone":"+919000000099"}'
    Assert "JSON body is sent as application/json" ($r.Status -eq 200 -and $r.Body -match '"a": 1' -and $r.Body -match '\+919000000099' -and $r.Body -match "application/json") "$($r.Body)"

    $r = Invoke-Http -Method OPTIONS -Uri "$base/cors" -Headers @{ Origin = "https://evil.example"; "Access-Control-Request-Method" = "GET" }
    Assert "CORS preflight: status and no allow-origin header" ($r.Status -eq 400 -and -not $r.Headers["Access-Control-Allow-Origin"]) "$($r.Status)"

    $threw = $false
    try { Invoke-Http -Method GET -Uri "http://127.0.0.1:1/unreachable" -TimeoutSec 5 | Out-Null } catch { $threw = $true }
    Assert "no HTTP answer at all still throws (not a fake status)" $threw
} finally {
    if (-not $server.HasExited) { $server.Kill() }
}
if ($failed -gt 0) { Write-Host "`n$failed test(s) FAILED" -ForegroundColor Red; exit 1 }
Write-Host "`nAll Invoke-Http tests passed." -ForegroundColor Green
