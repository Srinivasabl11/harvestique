# HTTP helper for the production scripts that works the same on Windows PowerShell 5.1 and PowerShell 7.
#
# Invoke-WebRequest on 5.1 loses the body of 4xx/5xx answers in some cases and, with -MaximumRedirection 0, throws an
# error that carries no response for a 301, so a redirect looked like "status 0". This uses HttpWebRequest directly and
# always returns what the server actually sent: @{ Status = <int>; Body = <string>; Headers = <WebHeaderCollection> }.
# It throws only when there is no HTTP answer at all (DNS, TLS or connection failure, timeout).

# Allow TLS 1.2 on 5.1 (older .NET defaults may not offer it); existing protocols are kept, nothing is removed.
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12

function Invoke-Http {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [string]$Json = $null,
        [hashtable]$Headers = @{},
        [switch]$NoRedirect,
        [int]$TimeoutSec = 120
    )
    $req = [System.Net.HttpWebRequest]::Create($Uri)
    $req.Method = $Method
    $req.Timeout = $TimeoutSec * 1000
    $req.ReadWriteTimeout = $TimeoutSec * 1000
    $req.AllowAutoRedirect = -not $NoRedirect
    $req.Accept = "application/json"
    foreach ($name in $Headers.Keys) { $req.Headers[$name] = [string]$Headers[$name] }
    if ($Json) {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)
        $req.ContentType = "application/json"
        $req.ContentLength = $bytes.Length
        $stream = $req.GetRequestStream()
        try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Close() }
    }
    $resp = $null
    try {
        $resp = $req.GetResponse()
    } catch {
        # 4xx/5xx (and 3xx when not following) arrive as a WebException that still holds the response
        $e = $_.Exception
        while ($e -and -not ($e -is [System.Net.WebException])) { $e = $e.InnerException }
        if ($null -eq $e -or $null -eq $e.Response) { throw }
        $resp = $e.Response
    }
    try {
        $reader = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
        try { $body = $reader.ReadToEnd() } finally { $reader.Close() }
        return @{ Status = [int]$resp.StatusCode; Body = $body; Headers = $resp.Headers }
    } finally {
        $resp.Close()
    }
}
