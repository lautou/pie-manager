# PIE Manager launcher — starts services then opens Edge in app mode
$pieManager = Join-Path $PSScriptRoot "pie-manager.exe"
$url = "http://localhost:14943"

# Start containers in background (silent)
Start-Process -WindowStyle Hidden $pieManager "start"

# Wait for the app to be ready (up to 90s)
for ($i = 0; $i -lt 90; $i++) {
    try {
        Invoke-WebRequest -Uri "$url/api/admin/version" -TimeoutSec 1 -UseBasicParsing -EA Stop | Out-Null
        break
    } catch { Start-Sleep 1 }
}

# Open Edge in app mode (no address bar), fallback to default browser
$edgePaths = @(
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)
$edge = $edgePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($edge) {
    Start-Process $edge "--app=$url", "--window-size=1400,900"
} else {
    Start-Process $url
}
