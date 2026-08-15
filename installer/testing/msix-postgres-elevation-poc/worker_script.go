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

# Flushed to $ResultPath after every major step (not just once at the very end) so a live
# poll of result.txt from outside the package shows real-time progress instead of the stale
# main.go "STARTED" marker for the whole run - the only way a prior hung run (stuck somewhere
# between pg_ctl start and the Python copy step, with near-zero CPU for 8+ minutes) could be
# externally localized was indirect process/thread inspection, which was inconclusive.
function Flush-Lines {
    Set-Content -Path $ResultPath -Value ($lines -join [Environment]::NewLine) -Encoding UTF8
}

$lines += "STARTED $(Get-Date -Format o)"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$lines += "USER: $($identity.Name)"
$lines += "IS_ADMIN_ROLE: $isAdmin"
$lines += "PKG_ROOT: $PkgRoot"
$lines += "PGDATA: $PgData"
Flush-Lines

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
Flush-Lines

$pgBin = Join-Path $localPgsql "bin"
$initdb = Join-Path $pgBin "initdb.exe"
$pgctl = Join-Path $pgBin "pg_ctl.exe"
$lines += "PGBIN_SOURCE: $pgBin"
$lines += "INITDB_EXE_EXISTS: $(Test-Path $initdb)"
$lines += "PGCTL_EXE_EXISTS: $(Test-Path $pgctl)"
Flush-Lines

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
Flush-Lines

$startExit = $null
if ($initdbExit -eq 0) {
    $startOut = Join-Path $logDir "msix-poc-pgctl-start.out.log"
    $startErr = Join-Path $logDir "msix-poc-pgctl-start.err.log"
    Remove-Item $startOut, $startErr -ErrorAction SilentlyContinue
    $startArgs = @("-D", $PgData, "-w", "start")
    try {
        # -Wait (not -PassThru's own timed WaitForExit) hung indefinitely here on a real run:
        # confirmed live via process inspection that pg_ctl.exe itself had already exited (gone
        # from Get-Process) while Start-Process never returned. Root cause: pg_ctl start spawns
        # postgres.exe, which inherits pg_ctl's redirected stdout/stderr handles and keeps them
        # open for as long as postgres (and its background workers) keep running - .NET's
        # parameterless Process.WaitForExit(), which -Wait uses internally, waits for the
        # redirected stream to reach EOF, not just for the process handle to signal, so it
        # blocks forever as long as any handle-inheriting descendant is still alive. The timed
        # overload, WaitForExit(ms), only waits on the process handle and has no such hazard.
        $startProc = Start-Process -FilePath $pgctl -ArgumentList $startArgs -NoNewWindow -PassThru -RedirectStandardOutput $startOut -RedirectStandardError $startErr
        if ($startProc.WaitForExit(60000)) {
            $startProc.Refresh()
            $startExit = $startProc.ExitCode
        } else {
            $lines += "PGCTL_START_WAIT_TIMEOUT: pg_ctl.exe still running after 60s"
        }
    } catch {
        $lines += "PGCTL_START_EXCEPTION: $($_.Exception.Message)"
    }
    $lines += "PGCTL_START_EXIT: $startExit"
    $lines += "--- PGCTL_START_STDOUT ---"
    $lines += @(Get-Content $startOut -ErrorAction SilentlyContinue)
    $lines += "--- PGCTL_START_STDERR ---"
    $lines += @(Get-Content $startErr -ErrorAction SilentlyContinue)

    # ExitCode came back empty/unreadable on a real run even though WaitForExit(60000) returned
    # true and the captured stdout clearly showed "serveur d�marr�" (server started) - a .NET
    # Process object obtained via Start-Process -PassThru doesn't always reliably expose
    # ExitCode after a timed (non-default) WaitForExit overload. postmaster.pid is written by
    # pg_ctl only on a genuinely successful start and is locale-independent, unlike parsing
    # stdout text - use its presence as a fallback success signal when ExitCode is unusable.
    $postmasterPidExists = Test-Path (Join-Path $PgData "postmaster.pid")
    $lines += "POSTMASTER_PID_EXISTS: $postmasterPidExists"
    if ($startExit -ne 0 -and $postmasterPidExists) {
        $lines += "PGCTL_START_EXIT_FALLBACK: treating as success via postmaster.pid presence (ExitCode was $startExit)"
        $startExit = 0
    }
    Flush-Lines

    if ($startExit -eq 0) {
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
        Flush-Lines

        $pythonExe = Join-Path $localPython "python.exe"
        $pgqExe = Join-Path $localPython "Scripts\pgq.exe"
        $psqlExe = Join-Path $pgBin "psql.exe"
        $lines += "PYTHON_EXE_EXISTS: $(Test-Path $pythonExe)"
        $lines += "PGQ_EXE_EXISTS: $(Test-Path $pgqExe)"
        Flush-Lines

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

        # Standard libpq env vars, not a --pg-dsn/--pg-host CLI flag: pgqueuer's CLI flags for
        # this have changed across versions (recent releases dropped --pg-host/--pg-user in
        # favor of env vars entirely), so env vars are the version-stable way to point both
        # install and run at the bundled Postgres.
        $env:PGHOST = "127.0.0.1"
        $env:PGPORT = "5432"
        $env:PGUSER = "pie"
        $env:PGDATABASE = "postgres"

        # pgq install (schema/table creation, including pgqueuer_schedules) must run before
        # pgq run - the real backend gets this via its own Alembic migrations, which this
        # throwaway script has none of. Invoked as python -m pgqueuer, not the pip-generated
        # pgq.exe launcher, for both this and the run step below: console-script .exe
        # launchers can embed an absolute build-time interpreter path that breaks once the
        # whole python/ folder is relocated (CI build path -> LocalState at runtime) - python
        # -m pgqueuer is documented as fully equivalent and always uses the actual relocated
        # interpreter it's invoked through.
        $pgqInstallOut = Join-Path $logDir "msix-poc-pgq-install.out.log"
        $pgqInstallErr = Join-Path $logDir "msix-poc-pgq-install.err.log"
        $installExit = $null
        try {
            $installProc = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "pgqueuer", "install") -NoNewWindow -PassThru -RedirectStandardOutput $pgqInstallOut -RedirectStandardError $pgqInstallErr
            if ($installProc.WaitForExit(30000)) {
                $installProc.Refresh()
                $installExit = $installProc.ExitCode
            } else {
                $lines += "PGQ_INSTALL_WAIT_TIMEOUT: still running after 30s"
            }
        } catch {
            $lines += "PGQ_INSTALL_EXCEPTION: $($_.Exception.Message)"
        }
        $lines += "PGQ_INSTALL_EXIT: $installExit"
        $lines += "--- PGQ_INSTALL_STDOUT ---"
        $lines += @(Get-Content $pgqInstallOut -ErrorAction SilentlyContinue)
        $lines += "--- PGQ_INSTALL_STDERR ---"
        $lines += @(Get-Content $pgqInstallErr -ErrorAction SilentlyContinue)
        Flush-Lines

        $pgqOut = Join-Path $logDir "msix-poc-pgq.out.log"
        $pgqErr = Join-Path $logDir "msix-poc-pgq.err.log"
        Remove-Item $pgqOut, $pgqErr -ErrorAction SilentlyContinue

        $pgqInstallExit = $null
        try {
            $pgqInstallProc = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "pgqueuer", "run", "pgq_test:main", "--log-level=INFO") -NoNewWindow -PassThru -WorkingDirectory $logDir -RedirectStandardOutput $pgqOut -RedirectStandardError $pgqErr
            Start-Sleep -Seconds 8
            if (-not $pgqInstallProc.HasExited) {
                Stop-Process -Id $pgqInstallProc.Id -Force -ErrorAction SilentlyContinue
                $pgqInstallExit = "RUNNING_THEN_STOPPED"
            } else {
                $pgqInstallProc.Refresh()
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
        Flush-Lines

        $scheduleCountRaw = & $psqlExe -U pie -d postgres -h 127.0.0.1 -t -c "SELECT count(*) FROM pgqueuer_schedules WHERE entrypoint='poc_test_entrypoint'" 2>&1
        $scheduleCountTrimmed = ($scheduleCountRaw -join " ").Trim()
        # -eq, not -match: a -match "1" false-matched the digit inside an unrelated "LIGNE 1"
        # substring of a real Postgres error message on a run where the schedules table didn't
        # exist yet (before this install step was added) - confirmed live, a real bug that
        # made a genuine failure report as PGQ_SCHEDULE_REGISTERED: True.
        $scheduleRegistered = $scheduleCountTrimmed -eq "1"
        $lines += "PGQ_SCHEDULE_REGISTERED: $scheduleRegistered (raw: $scheduleCountRaw)"
        Flush-Lines

        if ($scheduleRegistered) {
            $pgqVerdict = "SUCCESS: PgQueuer (embeddable Python) registered a real schedule against the bundled Postgres, non-elevated, from inside the MSIX package"
        } else {
            $pgqVerdict = "FAILURE: schedule was not found in pgqueuer_schedules - see PGQ_STDOUT/STDERR above"
        }
        $lines += "PGQUEUER_VERDICT: $pgqVerdict"
        Flush-Lines

        # The real backend (FastAPI/uvicorn) itself, plus serving a pre-built frontend via
        # StaticFiles - issue #65's target architecture, neither of which the Postgres/PgQueuer
        # checks above exercise at all. Bundled Python above already has the REAL backend's
        # full requirements.txt installed (not just pgqueuer/asyncpg), so this also proves the
        # whole dependency tree (uvicorn[standard]'s optional extras included) installs and
        # imports cleanly in an embeddable, relocated Python. No DB access in the test app
        # itself - Postgres connectivity is already proven above, this is scoped to the
        # web-serving path alone.
        $staticDir = Join-Path $logDir "static_test"
        New-Item -ItemType Directory -Force -Path $staticDir | Out-Null
        Set-Content -Path (Join-Path $staticDir "index.html") -Value "MSIX_POC_STATIC_OK"

        $fastapiTestScript = @'
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import pathlib

app = FastAPI()

@app.get("/api/health")
async def health():
    return {"status": "ok"}

_static_dir = pathlib.Path(__file__).parent / "static_test"
app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
'@
        $fastapiTestPath = Join-Path $logDir "fastapi_test.py"
        Set-Content -Path $fastapiTestPath -Value $fastapiTestScript

        $uvicornOut = Join-Path $logDir "msix-poc-uvicorn.out.log"
        $uvicornErr = Join-Path $logDir "msix-poc-uvicorn.err.log"
        Remove-Item $uvicornOut, $uvicornErr -ErrorAction SilentlyContinue

        $healthOk = $false
        $healthRaw = $null
        $staticOk = $false
        $staticRaw = $null
        $uvicornExit = $null
        try {
            $uvicornProc = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "uvicorn", "fastapi_test:app", "--host", "127.0.0.1", "--port", "8123", "--log-level", "info") -NoNewWindow -PassThru -WorkingDirectory $logDir -RedirectStandardOutput $uvicornOut -RedirectStandardError $uvicornErr
            Start-Sleep -Seconds 6

            try {
                $healthResp = Invoke-WebRequest -Uri "http://127.0.0.1:8123/api/health" -UseBasicParsing -TimeoutSec 10
                $healthRaw = $healthResp.Content
                $healthOk = ($healthResp.StatusCode -eq 200) -and ($healthRaw -match '"status"\s*:\s*"ok"')
            } catch {
                $lines += "WEBSERVER_HEALTH_EXCEPTION: $($_.Exception.Message)"
            }
            $lines += "WEBSERVER_HEALTH_OK: $healthOk (raw: $healthRaw)"

            try {
                $staticResp = Invoke-WebRequest -Uri "http://127.0.0.1:8123/" -UseBasicParsing -TimeoutSec 10
                $staticRaw = $staticResp.Content
                $staticOk = ($staticResp.StatusCode -eq 200) -and ($staticRaw -match "MSIX_POC_STATIC_OK")
            } catch {
                $lines += "WEBSERVER_STATIC_EXCEPTION: $($_.Exception.Message)"
            }
            $lines += "WEBSERVER_STATIC_OK: $staticOk (raw: $staticRaw)"

            if (-not $uvicornProc.HasExited) {
                $uvicornExit = "RUNNING_THEN_STOPPED"
                Stop-Process -Id $uvicornProc.Id -Force -ErrorAction SilentlyContinue
            } else {
                $uvicornProc.Refresh()
                $uvicornExit = $uvicornProc.ExitCode
            }
        } catch {
            $lines += "WEBSERVER_LAUNCH_EXCEPTION: $($_.Exception.Message)"
        }
        $lines += "UVICORN_RUN_RESULT: $uvicornExit"
        $lines += "--- UVICORN_STDOUT ---"
        $lines += @(Get-Content $uvicornOut -ErrorAction SilentlyContinue)
        $lines += "--- UVICORN_STDERR ---"
        $lines += @(Get-Content $uvicornErr -ErrorAction SilentlyContinue)
        Flush-Lines

        if ($healthOk -and $staticOk) {
            $webserverVerdict = "SUCCESS: FastAPI/uvicorn served both a real API endpoint and a static file, non-elevated, from inside the MSIX package"
        } else {
            $webserverVerdict = "FAILURE: health=$healthOk static=$staticOk - see UVICORN_STDOUT/STDERR above"
        }
        $lines += "WEBSERVER_VERDICT: $webserverVerdict"
        Flush-Lines

        $stopOut = Join-Path $logDir "msix-poc-pgctl-stop.out.log"
        $stopErr = Join-Path $logDir "msix-poc-pgctl-stop.err.log"
        # Same -PassThru + timed WaitForExit as pg_ctl start above, not -Wait - stop's own
        # target processes normally die before pg_ctl itself exits (closing the inherited
        # handle for real), but there's no reason to keep the hazard around when the fix is
        # this cheap.
        $stopProc = Start-Process -FilePath $pgctl -ArgumentList @("-D", $PgData, "-w", "stop") -NoNewWindow -PassThru -RedirectStandardOutput $stopOut -RedirectStandardError $stopErr
        if (-not $stopProc.WaitForExit(60000)) {
            $lines += "PGCTL_STOP_WAIT_TIMEOUT: pg_ctl.exe still running after 60s"
        }
        Flush-Lines
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
Flush-Lines
`
