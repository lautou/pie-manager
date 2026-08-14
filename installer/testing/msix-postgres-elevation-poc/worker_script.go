package main

// workerScript is the actual test logic, run via `powershell.exe -File` (never -Command with
// inline substitution — see main.go's comment on why). $PkgRoot/$PgData/$ResultPath arrive as
// ordinary bound parameters, so paths containing spaces need no manual escaping. Uses a plain
// array with += instead of System.Collections.Generic.List[string] — `New-Object
// System.Collections.Generic.List[string]` (unquoted generic type argument) is a known
// Windows PowerShell 5.1 parsing ambiguity; a plain array avoids that whole class of risk for
// the handful of lines this script ever accumulates.
const workerScript = `
param(
    [Parameter(Mandatory=$true)][string]$PkgRoot,
    [Parameter(Mandatory=$true)][string]$PgData,
    [Parameter(Mandatory=$true)][string]$ResultPath
)

$lines = @()
$lines += "STARTED $(Get-Date -Format o)"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$lines += "USER: $($identity.Name)"
$lines += "IS_ADMIN_ROLE: $isAdmin"
$lines += "PKG_ROOT: $PkgRoot"
$lines += "PGDATA: $PgData"

$pgBin = Join-Path $PkgRoot "pgsql\bin"
$initdb = Join-Path $pgBin "initdb.exe"
$pgctl = Join-Path $pgBin "pg_ctl.exe"

New-Item -ItemType Directory -Force -Path (Split-Path $PgData -Parent) | Out-Null

$logDir = Split-Path $ResultPath -Parent
$initdbLog = Join-Path $logDir "msix-poc-initdb.log"
Remove-Item $initdbLog -ErrorAction SilentlyContinue
& $initdb -D $PgData -U pie --auth=trust *> $initdbLog
$initdbExit = $LASTEXITCODE
$lines += "INITDB_EXIT: $initdbExit"
$lines += "--- INITDB_OUTPUT ---"
$lines += @(Get-Content $initdbLog -ErrorAction SilentlyContinue)

$startExit = $null
if ($initdbExit -eq 0) {
    $startLog = Join-Path $logDir "msix-poc-pgctl-start.log"
    Remove-Item $startLog -ErrorAction SilentlyContinue
    & $pgctl -D $PgData -l $startLog -w start
    $startExit = $LASTEXITCODE
    $lines += "PGCTL_START_EXIT: $startExit"
    $lines += "--- PGCTL_START_LOG ---"
    $lines += @(Get-Content $startLog -ErrorAction SilentlyContinue)

    if ($startExit -eq 0) {
        & $pgctl -D $PgData status
        $lines += "PGCTL_STATUS_EXIT: $LASTEXITCODE"
        & $pgctl -D $PgData stop -w
        $lines += "PGCTL_STOP_EXIT: $LASTEXITCODE"
    }
} else {
    $lines += "PGCTL_START_EXIT: SKIPPED (initdb failed)"
}

if ($initdbExit -eq 0 -and $startExit -eq 0) {
    $verdict = "SUCCESS: postgres started with no elevation issue (IS_ADMIN_ROLE=$isAdmin)"
} elseif ($isAdmin -eq $true) {
    $verdict = "EXPECTED_FAILURE: blocked while IS_ADMIN_ROLE=True (matches PostgreSQL's documented admin-refusal behavior - this is the known negative control, not a surprise)"
} else {
    $verdict = "UNEXPECTED_FAILURE: blocked while IS_ADMIN_ROLE=False (does NOT match the known admin-refusal cause - investigate separately, likely an MSIX path/permission issue unrelated to elevation)"
}
$lines += "VERDICT: $verdict"

Set-Content -Path $ResultPath -Value ($lines -join [Environment]::NewLine) -Encoding UTF8
`
