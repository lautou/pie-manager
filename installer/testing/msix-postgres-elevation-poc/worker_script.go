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

New-Item -ItemType Directory -Force -Path (Split-Path $PgData -Parent) | Out-Null

# A prior run got "Access is denied" trying to Start-Process a bundled initdb.exe directly from
# the package's own install directory (under C:\Program Files\WindowsApps\...) — distinct from
# PostgreSQL's own admin-refusal message. Confirmed: Windows/MSIX restricts executing arbitrary
# bundled binaries in-place from a package's read-only, integrity-protected install directory,
# regardless of elevation. Fix: copy the whole pgsql folder (bin AND share together, preserving
# their sibling layout) into this package's own writable LocalState area first, and launch from
# there instead of from $PkgRoot. A first attempt at this copied only pgsql\bin, which let
# initdb launch (no more Access Denied) but then fail on "file /share/postgres.bki does not
# exist" — postgres.exe/initdb.exe locate share/ via a path relative to bin/, so partially
# copying just bin/ breaks that relative lookup against the share/ left behind in $PkgRoot.
# robocopy, not Copy-Item -Recurse: a later run bundling many more small files (the Python
# folder, see below) found Copy-Item -Recurse can hang indefinitely partway through a
# many-small-files tree on this VM's storage, with no exception and near-zero CPU use (blocked,
# not slow) — robocopy is the standard, far more robust tool for exactly this. /R:1 /W:1
# (1 retry, 1s wait) explicitly overrides robocopy's own well-known footgun default of
# effectively unlimited retries on a locked/inaccessible file, which would introduce the same
# class of hang risk right back. Exit codes 0-7 all mean success (varying detail); only 8+ is a
# real failure.
#
# Each path is wrapped in its own literal double-quotes (single-quoted PowerShell strings so
# the quote characters need no escaping) before going into -ArgumentList: a first attempt
# passed bare, unquoted paths in the array and Start-Process's array-to-command-line join did
# not reliably quote the one containing a space ("C:\Program Files\..."), which robocopy then
# silently mis-parsed as two separate positional arguments (confirmed via its own captured
# "ParamStre non valide #3" error - i.e. garbage source/destination split apart).
$localPgsql = Join-Path (Split-Path $PgData -Parent) "pgsql"
$pgsqlCopyOut = Join-Path (Split-Path $PgData -Parent) "robocopy-pgsql.log"
$pgsqlSrcQ = '"' + (Join-Path $PkgRoot "pgsql") + '"'
$pgsqlDstQ = '"' + $localPgsql + '"'
$pgsqlCopyProc = Start-Process -FilePath "robocopy.exe" -ArgumentList @($pgsqlSrcQ, $pgsqlDstQ, "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP") -NoNewWindow -Wait -PassThru -RedirectStandardOutput $pgsqlCopyOut -RedirectStandardError "$pgsqlCopyOut.err"
$lines += "COPY_PGSQL_TO_LOCALSTATE_ROBOCOPY_EXIT: $($pgsqlCopyProc.ExitCode)"

$pgBin = Join-Path $localPgsql "bin"
$initdb = Join-Path $pgBin "initdb.exe"
$pgctl = Join-Path $pgBin "pg_ctl.exe"
$lines += "PGBIN_SOURCE: $pgBin"
$lines += "INITDB_EXE_EXISTS: $(Test-Path $initdb)"
$lines += "PGCTL_EXE_EXISTS: $(Test-Path $pgctl)"

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
        # -RedirectStandardOutput/-Error here too: an earlier version left this call
        # unredirected, and it hung indefinitely (worker.ps1 accumulated ~5s of CPU time over
        # 8+ minutes of wall clock, i.e. blocked, not slow) — a process launched via
        # -NoNewWindow with no console and no redirected output can deadlock on WriteFile if
        # its stdout pipe buffer fills with nobody reading it, in this non-interactive
        # scheduled-task-launched-with-an-interactive-token context.
        $statusOut = Join-Path $logDir "msix-poc-pgctl-status.out.log"
        $statusErr = Join-Path $logDir "msix-poc-pgctl-status.err.log"
        Start-Process -FilePath $pgctl -ArgumentList @("-D", $PgData, "status") -NoNewWindow -Wait -RedirectStandardOutput $statusOut -RedirectStandardError $statusErr

        # PgQueuer (the Celery/Redis replacement, issue #66) — same LocalState-copy pattern as
        # pgsql above (robocopy, not Copy-Item -Recurse — see that step's comment for why): the
        # bundled embeddable Python/pgq.exe can't run in-place from the package's own read-only
        # install directory either. This is the copy that first exposed the Copy-Item hang (a
        # Python install's site-packages tree has far more, smaller files than pgsql's).
        $localPython = Join-Path (Split-Path $PgData -Parent) "python"
        $pyCopyOut = Join-Path (Split-Path $PgData -Parent) "robocopy-python.log"
        $pySrcQ = '"' + (Join-Path $PkgRoot "python") + '"'
        $pyDstQ = '"' + $localPython + '"'
        $pyCopyProc = Start-Process -FilePath "robocopy.exe" -ArgumentList @($pySrcQ, $pyDstQ, "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP") -NoNewWindow -Wait -PassThru -RedirectStandardOutput $pyCopyOut -RedirectStandardError "$pyCopyOut.err"
        $lines += "COPY_PYTHON_TO_LOCALSTATE_ROBOCOPY_EXIT: $($pyCopyProc.ExitCode)"

        $pythonExe = Join-Path $localPython "python.exe"
        $pgqExe = Join-Path $localPython "Scripts\pgq.exe"
        $psqlExe = Join-Path $pgBin "psql.exe"
        $lines += "PYTHON_EXE_EXISTS: $(Test-Path $pythonExe)"
        $lines += "PGQ_EXE_EXISTS: $(Test-Path $pgqExe)"

        # Minimal, self-contained mirror of the real app.tasks.pgq_app:main shape (see that
        # file's own asynccontextmanager main()) - registers one schedule against the same
        # Postgres instance just started above, without needing the whole backend bundled.
        $pgqTestScript = @'
from contextlib import asynccontextmanager
import asyncpg
from pgqueuer import PgQueuer
from pgqueuer.domain.models import Schedule

@asynccontextmanager
async def main():
    conn = await asyncpg.connect(dsn="postgresql://pie@127.0.0.1:5432/postgres")
    try:
        pgq = PgQueuer.from_asyncpg_connection(conn)

        @pgq.schedule("poc_test_entrypoint", "* * * * *")
        async def _test_schedule(schedule: Schedule) -> None:
            pass

        yield pgq
    finally:
        await conn.close()
'@
        $pgqTestPath = Join-Path $logDir "pgq_test.py"
        Set-Content -Path $pgqTestPath -Value $pgqTestScript

        $pgqOut = Join-Path $logDir "msix-poc-pgq.out.log"
        $pgqErr = Join-Path $logDir "msix-poc-pgq.err.log"
        Remove-Item $pgqOut, $pgqErr -ErrorAction SilentlyContinue

        $pgqInstallExit = $null
        try {
            $pgqInstallProc = Start-Process -FilePath $pgqExe -ArgumentList @("run", "pgq_test:main", "--log-level=INFO") -NoNewWindow -PassThru -WorkingDirectory $logDir -RedirectStandardOutput $pgqOut -RedirectStandardError $pgqErr
            Start-Sleep -Seconds 8
            if (-not $pgqInstallProc.HasExited) {
                Stop-Process -Id $pgqInstallProc.Id -Force -ErrorAction SilentlyContinue
                $pgqInstallExit = "RUNNING_THEN_STOPPED"
            } else {
                $pgqInstallExit = $pgqInstallProc.ExitCode
            }
        } catch {
            $lines += "PGQ_RUN_EXCEPTION: $($_.Exception.Message)"
        }
        $lines += "PGQ_RUN_RESULT: $pgqInstallExit"
        $lines += "--- PGQ_STDOUT ---"
        $lines += @(Get-Content $pgqOut -ErrorAction SilentlyContinue)
        $lines += "--- PGQ_STDERR ---"
        $lines += @(Get-Content $pgqErr -ErrorAction SilentlyContinue)

        $scheduleCountRaw = & $psqlExe -U pie -d postgres -h 127.0.0.1 -t -c "SELECT count(*) FROM pgqueuer_schedules WHERE entrypoint='poc_test_entrypoint'" 2>&1
        $scheduleRegistered = ($scheduleCountRaw -join " ").Trim() -match "1"
        $lines += "PGQ_SCHEDULE_REGISTERED: $scheduleRegistered (raw: $scheduleCountRaw)"

        if ($scheduleRegistered) {
            $pgqVerdict = "SUCCESS: PgQueuer (embeddable Python) registered a real schedule against the bundled Postgres, non-elevated, from inside the MSIX package"
        } else {
            $pgqVerdict = "FAILURE: schedule was not found in pgqueuer_schedules - see PGQ_STDOUT/STDERR above"
        }
        $lines += "PGQUEUER_VERDICT: $pgqVerdict"

        $stopOut = Join-Path $logDir "msix-poc-pgctl-stop.out.log"
        $stopErr = Join-Path $logDir "msix-poc-pgctl-stop.err.log"
        Start-Process -FilePath $pgctl -ArgumentList @("-D", $PgData, "-w", "stop") -NoNewWindow -Wait -RedirectStandardOutput $stopOut -RedirectStandardError $stopErr
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
