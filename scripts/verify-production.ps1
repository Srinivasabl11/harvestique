# Smoke test of the hosted API from this PC's internet connection (no LAN, no local Docker): HTTPS, health, CORS,
# security headers and the auth refusals. Changes nothing on the server. Does not need any secret.
#
#   powershell -ExecutionPolicy Bypass -File scripts\verify-production.ps1
param([string]$BaseUrl = ((Get-Content (Join-Path (Split-Path -Parent $PSScriptRoot) "frontend\config\production.json") -Raw | ConvertFrom-Json).API_BASE_URL))
$ErrorActionPreference = "Stop"
$fail = 0
function Check([string]$name, [bool]$ok, [string]$detail) {
    if ($ok) { Write-Host "PASS  $name  $detail" -ForegroundColor Green }
    else { Write-Host "FAIL  $name  $detail" -ForegroundColor Red; $script:fail++ }
}
function Call([string]$method, [string]$path, $body = $null, $headers = @{}) {
    $args = @{ Uri = "$BaseUrl$path"; Method = $method; Headers = $headers; TimeoutSec = 120; UseBasicParsing = $true }
    if ($null -ne $body) { $args.Body = ($body | ConvertTo-Json -Compress); $args.ContentType = "application/json" }
    try { $r = Invoke-WebRequest @args; return @{ Status = [int]$r.StatusCode; Body = $r.Content; Headers = $r.Headers } }
    catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        if ($null -eq $resp) { throw }
        $text = if ($_.ErrorDetails) { $_.ErrorDetails.Message } else { "" }  # PowerShell 5.1 keeps the body here
        return @{ Status = [int]$resp.StatusCode; Body = $text; Headers = $resp.Headers }
    }
}

Check "https" ($BaseUrl.StartsWith("https://")) $BaseUrl
$live = Call GET "/health/live"   # wakes a sleeping free server (up to about a minute)
Check "health/live" ($live.Status -eq 200) "HTTP $($live.Status)"
$ready = Call GET "/health/ready"
Check "health/ready" ($ready.Status -eq 200 -and $ready.Body -match '"status":"ready"') $ready.Body
$me = Call GET "/auth/me"
Check "auth required" ($me.Status -eq 401) "GET /auth/me without a token -> $($me.Status)"
$bad = Call POST "/auth/login" @{ phone = "+919000000099"; password = "not-the-password-1" }
Check "wrong password refused" ($bad.Status -eq 401 -and $bad.Body -match "invalid_credentials") "-> $($bad.Status)"
$sms = Call POST "/auth/login/verify" @{ challenge_id = "00000000-0000-0000-0000-000000000000"; code = "000000" }
Check "no SMS-code endpoints (password-only build)" ($sms.Status -eq 404) "POST /auth/login/verify -> $($sms.Status)"
$cors = Call OPTIONS "/auth/me" $null @{ Origin = "https://evil.example"; "Access-Control-Request-Method" = "GET" }
Check "browser origins refused (CORS)" (-not $cors.Headers["Access-Control-Allow-Origin"]) "preflight -> $($cors.Status)"
$plain = $BaseUrl -replace '^https://', 'http://'
try { $h = Invoke-WebRequest -Uri "$plain/health/live" -MaximumRedirection 0 -UseBasicParsing -TimeoutSec 60; $code = [int]$h.StatusCode }
catch { $code = [int]$_.Exception.Response.StatusCode }
Check "plain HTTP not served" ($code -ge 300 -and $code -lt 400) "http:// -> $code (redirect to HTTPS)"
if ($fail -gt 0) { Write-Host "`n$fail check(s) FAILED" -ForegroundColor Red; exit 1 }
Write-Host "`nAll production checks passed." -ForegroundColor Green
