package main

// workerScript is the actual test logic, run via `powershell.exe -File` (never -Command with
// inline substitution — see main.go's comment on why). $PkgRoot/$PgData/$ResultPath arrive as
// ordinary bound parameters, so paths containing spaces need no manual escaping. Uses a plain
// array with += instead of System.Collections.Generic.List[string] — `New-Object
// System.Collections.Generic.List[string]` (unquoted generic type argument) is a known
// Windows PowerShell 5.1 parsing ambiguity; a plain array avoids that whole class of risk for
// the handful of lines this script ever accumulates.
//
// Native processes are launched via Start-Process -PassThru -Wait with explicit
// -RedirectStandardOutput/-RedirectStandardError, not `& $exe ... *> file` — a first version
// used the `&`/`*>` pattern and it left INITDB_EXIT and the captured output both completely
// empty despite the run correctly reaching a VERDICT, which isn't good enough evidence to
// confirm the failure was PostgreSQL's own admin-refusal specifically (vs. e.g. Defender/AV
// silently blocking a freshly-signed, unknown binary from running at all — a distinct failure
// mode that would also correlate with IS_ADMIN_ROLE=True by coincidence on this runner).
// Start-Process's own ExitCode/redirected-file mechanism is the reliable way to capture both
// for a native child process in PowerShell.
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
$lines += "INITDB_EXE_EXISTS: $(Test-Path $initdb)"
$lines += "PGCTL_EXE_EXISTS: $(Test-Path $pgctl)"
$lines += "PGBIN_LISTING:"
$lines += @(Get-ChildItem $pgBin -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)

New-Item -ItemType Directory -Force -Path (Split-Path $PgData -Parent) | Out-Null

$logDir = Split-Path $ResultPath -Parent
$initdbOut = Join-Path $logDir "msix-poc-initdb.out.log"
$initdbErr = Join-Path $logDir "msix-poc-initdb.err.log"
Remove-Item $initdbOut, $initdbErr -ErrorAction SilentlyContinue

$initdbArgs = @("-D", $PgData, "-U", "pie", "--auth=trust")
$initdbExit = $null
try {
    $initdbProc = Start-Process -FilePath $initdb -ArgumentList $initdbArgs -NoNewWindow -Wait -PassThru -RedirectStandardOutput $initdbOut -RedirectStandardError $initdbErr
    $initdbExit = $initdbProc.ExitCode
} catch {
    $lines += "INITDB_START_EXCEPTION: $($_.Exception.Message)"
}
$lines += "INITDB_EXIT: $initdbExit"
$lines += "--- INITDB_STDOUT ---"
$lines += @(Get-Content $initdbOut -ErrorAction SilentlyContinue)
$lines += "--- INITDB_STDERR ---"
$initdbStderr = @(Get-Content $initdbErr -ErrorAction SilentlyContinue)
$lines += $initdbStderr
$adminRefusalSeen = ($initdbStderr -join [Environment]::NewLine) -match "administrative permissions is not permitted"
$lines += "INITDB_ADMIN_REFUSAL_MESSAGE_SEEN: $adminRefusalSeen"

$startExit = $null
if ($initdbExit -eq 0) {
    $startOut = Join-Path $logDir "msix-poc-pgctl-start.out.log"
    $startErr = Join-Path $logDir "msix-poc-pgctl-start.err.log"
    Remove-Item $startOut, $startErr -ErrorAction SilentlyContinue
    $startArgs = @("-D", $PgData, "-w", "start")
    try {
        $startProc = Start-Process -FilePath $pgctl -ArgumentList $startArgs -NoNewWindow -Wait -PassThru -RedirectStandardOutput $startOut -RedirectStandardError $startErr
        $startExit = $startProc.ExitCode
    } catch {
        $lines += "PGCTL_START_EXCEPTION: $($_.Exception.Message)"
    }
    $lines += "PGCTL_START_EXIT: $startExit"
    $lines += "--- PGCTL_START_STDOUT ---"
    $lines += @(Get-Content $startOut -ErrorAction SilentlyContinue)
    $lines += "--- PGCTL_START_STDERR ---"
    $lines += @(Get-Content $startErr -ErrorAction SilentlyContinue)

    if ($startExit -eq 0) {
        Start-Process -FilePath $pgctl -ArgumentList @("-D", $PgData, "status") -NoNewWindow -Wait
        Start-Process -FilePath $pgctl -ArgumentList @("-D", $PgData, "-w", "stop") -NoNewWindow -Wait
    }
} else {
    $lines += "PGCTL_START_EXIT: SKIPPED (initdb failed)"
}

if ($initdbExit -eq 0 -and $startExit -eq 0) {
    $verdict = "SUCCESS: postgres started with no elevation issue (IS_ADMIN_ROLE=$isAdmin)"
} elseif ($adminRefusalSeen) {
    $verdict = "EXPECTED_FAILURE: initdb printed PostgreSQL's own admin-refusal message while IS_ADMIN_ROLE=True (this is the known negative control, confirmed by message text, not just inferred from the account state)"
} elseif ($isAdmin -eq $true) {
    $verdict = "UNEXPECTED_FAILURE: blocked while IS_ADMIN_ROLE=True but WITHOUT PostgreSQL's own admin-refusal message text - some other cause (e.g. AV/Defender blocking the binary, a missing DLL) - investigate the captured stdout/stderr above"
} else {
    $verdict = "UNEXPECTED_FAILURE: blocked while IS_ADMIN_ROLE=False (does NOT match the known admin-refusal cause - investigate separately, likely an MSIX path/permission issue unrelated to elevation)"
}
$lines += "VERDICT: $verdict"

Set-Content -Path $ResultPath -Value ($lines -join [Environment]::NewLine) -Encoding UTF8
`
