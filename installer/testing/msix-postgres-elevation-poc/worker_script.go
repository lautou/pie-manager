package main

// workerScript is the actual test logic, run via `powershell.exe -File` (never -Command with
// inline substitution — see main.go's comment on why). $PkgRoot/$PgData/$ResultPath arrive as
// ordinary bound parameters, so paths containing spaces need no manual escaping.
const workerScript = `
param(
    [Parameter(Mandatory=$true)][string]$PkgRoot,
    [Parameter(Mandatory=$true)][string]$PgData,
    [Parameter(Mandatory=$true)][string]$ResultPath
)

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("STARTED $(Get-Date -Format o)")

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$lines.Add("USER: $($identity.Name)")
$lines.Add("IS_ADMIN_ROLE: $isAdmin")
$lines.Add("PKG_ROOT: $PkgRoot")
$lines.Add("PGDATA: $PgData")

$pgBin = Join-Path $PkgRoot "pgsql\bin"
$initdb = Join-Path $pgBin "initdb.exe"
$pgctl = Join-Path $pgBin "pg_ctl.exe"

New-Item -ItemType Directory -Force -Path (Split-Path $PgData -Parent) | Out-Null

$initdbLog = Join-Path $env:TEMP "msix-poc-initdb.log"
Remove-Item $initdbLog -ErrorAction SilentlyContinue
& $initdb -D $PgData -U pie --auth=trust *> $initdbLog
$initdbExit = $LASTEXITCODE
$lines.Add("INITDB_EXIT: $initdbExit")
$lines.Add("--- INITDB_OUTPUT ---")
Get-Content $initdbLog -ErrorAction SilentlyContinue | ForEach-Object { $lines.Add($_) }

$startExit = $null
if ($initdbExit -eq 0) {
    $startLog = Join-Path $env:TEMP "msix-poc-pgctl-start.log"
    Remove-Item $startLog -ErrorAction SilentlyContinue
    & $pgctl -D $PgData -l $startLog -w start
    $startExit = $LASTEXITCODE
    $lines.Add("PGCTL_START_EXIT: $startExit")
    $lines.Add("--- PGCTL_START_LOG ---")
    Get-Content $startLog -ErrorAction SilentlyContinue | ForEach-Object { $lines.Add($_) }

    if ($startExit -eq 0) {
        & $pgctl -D $PgData status
        $lines.Add("PGCTL_STATUS_EXIT: $LASTEXITCODE")
        & $pgctl -D $PgData stop -w
        $lines.Add("PGCTL_STOP_EXIT: $LASTEXITCODE")
    }
} else {
    $lines.Add("PGCTL_START_EXIT: SKIPPED (initdb failed)")
}

if ($initdbExit -eq 0 -and $startExit -eq 0) {
    $verdict = "SUCCESS: postgres started with no elevation issue (IS_ADMIN_ROLE=$isAdmin)"
} elseif ($isAdmin -eq $true) {
    $verdict = "EXPECTED_FAILURE: blocked while IS_ADMIN_ROLE=True (matches PostgreSQL's documented admin-refusal behavior — this is the known negative control, not a surprise)"
} else {
    $verdict = "UNEXPECTED_FAILURE: blocked while IS_ADMIN_ROLE=False (does NOT match the known admin-refusal cause — investigate separately, likely an MSIX path/permission issue unrelated to elevation)"
}
$lines.Add("VERDICT: $verdict")

Set-Content -Path $ResultPath -Value ($lines -join [Environment]::NewLine) -Encoding UTF8
`
