package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

// Version is injected at build time via -ldflags "-X main.Version=x.y.z". Declared here rather
// than in main.go (which is //go:build windows-only) so it stays available for `go vet`/`go
// test` on every platform — startBackend below needs it too, not just main.go's loading screen.
var Version = "dev"

func pythonExePath(home string) string { return filepath.Join(pythonDir(home), "python.exe") }

// backendAppDir is where the backend's Python source (the "app" package) is staged, alongside
// the embeddable interpreter's own site-packages, so "app.main" resolves via uvicorn's
// --app-dir without a separate PYTHONPATH configuration. Exactly how it gets staged there is a
// packaging-pipeline concern (issue #82's later "full MSIX packaging pipeline" step) - this
// orchestration code only needs to know where to find it once staged, the same way postgres.go
// doesn't know how pgBinDir's contents got there either.
func backendAppDir(home string) string { return pythonDir(home) }

// databaseURL builds the SQLAlchemy/asyncpg connection string for the bundled, trust-auth
// Postgres instance on its dynamically-selected port - no password, matching pgSuperuser's
// --auth=trust (see postgres.go).
func databaseURL(port int) string {
	return fmt.Sprintf("postgresql+asyncpg://%s@127.0.0.1:%d/%s", pgSuperuser, port, pgDatabaseName)
}

func buildUvicornArgs(home string, backendPort int) []string {
	return []string{
		"-m", "uvicorn", "app.main:app",
		"--app-dir", backendAppDir(home),
		"--host", "127.0.0.1",
		"--port", fmt.Sprintf("%d", backendPort),
	}
}

func healthURL(backendPort int) string {
	return fmt.Sprintf("http://127.0.0.1:%d/api/admin/version", backendPort)
}

func buildAlembicArgs() []string {
	return []string{"-m", "alembic", "upgrade", "head"}
}

// buildPgqueuerArgs invokes PgQueuer the same way this module already invokes uvicorn/alembic —
// via "-m modulename", not a generated Scripts/pgq.exe wrapper (see buildUvicornArgs/
// buildAlembicArgs above) — pgqueuer ships a real __main__.py, confirmed for the pinned
// pgqueuer==1.3.2. app.tasks.pgq_app:main registers all 6 real task handlers (price sync, ETF
// holdings, macro indicators, country performance, daily/monthly snapshots).
func buildPgqueuerArgs() []string {
	return []string{"-m", "pgqueuer", "run", "app.tasks.pgq_app:main"}
}

// migrationTimeout bounds runMigrations, deliberately far longer than postgres.go's
// processTimeout (60s, sized only for quick Postgres commands becoming ready). Root cause of
// issue #82's Microsoft Store certification failure: a first-run "alembic upgrade head" applies
// the project's entire migration history, and runMigrations used to share processTimeout via
// the same runCapturedCommandIn call - on the certification lab's locked-down machines this
// exceeded 60s (plausibly Windows Defender real-time-scanning the freshly-extracted embedded
// Python interpreter's many DLL/.pyd dependencies on first import), and Go's context timeout
// killed python.exe mid-migration (0xC000013A / STATUS_CONTROL_C_EXIT in the crash report).
// A measured from-scratch run of the full migration chain takes ~1-2s of actual work (Python
// startup + imports + all migrations, Linux, warm dependencies) - the DB work itself is not the
// bottleneck, so this budget only needs to be generous enough to absorb first-run environment
// overhead, not to match any real expected duration. No UX cost to a large value: main.go
// already shows a loading screen for the entire startup sequence.
const migrationTimeout = 10 * time.Minute

// runMigrations applies pending Alembic migrations - run on EVERY launch, not just first run,
// so an app update carrying new migrations gets them applied automatically the next time the
// user opens the app (mirrors compose-prod.yaml's own "alembic upgrade head && uvicorn" startup
// sequence, which runs unconditionally on every container start). alembic.ini's
// script_location ("alembic", a relative path) requires the working directory to be
// backendAppDir, where both alembic.ini and the alembic/ scripts folder are staged alongside
// the app package.
func runMigrations(home string, pgPort int) error {
	return runCapturedCommandIn(backendAppDir(home), []string{"DATABASE_URL=" + databaseURL(pgPort)}, migrationTimeout,
		pythonExePath(home), filepath.Join(logDir(home), "alembic.log"), buildAlembicArgs()...)
}

// startBackend spawns the bundled uvicorn as a long-lived child process (unlike postgres.go's
// run-to-completion commands) with DATABASE_URL pointing at the given Postgres port. Not
// unit-testable - a real external process spawn, same documented policy as postgres.go's
// process-spawning functions. The caller is responsible for eventually stopping the returned
// *exec.Cmd's process (see stopChildProcess).
//
// PATH is explicitly prefixed with pgBinDir so admin.py's backup/restore endpoints (which shell
// out to bare "pg_dump"/"pg_restore" by name, relying on PATH resolution — matching the
// container image, where postgresql-client tooling is already on PATH) can actually find our
// bundled pg_dump.exe/pg_restore.exe (issue #83). Without this, the OS-inherited PATH from
// os.Environ() has no reason to include our data directory's pgsql\bin, and both endpoints would
// fail outright with a bare "command not found" on a real install — never caught by CI, which
// doesn't yet exercise this launcher's backup/restore path end-to-end (see issue #114).
func startBackend(home string, backendPort, pgPort int) (*exec.Cmd, error) {
	if err := os.MkdirAll(logDir(home), 0o755); err != nil {
		return nil, fmt.Errorf("creating log directory: %w", err)
	}
	out, err := os.Create(filepath.Join(logDir(home), "backend.log"))
	if err != nil {
		return nil, fmt.Errorf("creating backend log: %w", err)
	}

	cmd := exec.Command(pythonExePath(home), buildUvicornArgs(home, backendPort)...)
	hideWindow(cmd)
	cmd.Env = append(os.Environ(),
		"DATABASE_URL="+databaseURL(pgPort),
		"FRONTEND_DIST_DIR="+frontendDistDir(home),
		"PATH="+pgBinDir(home)+string(os.PathListSeparator)+os.Getenv("PATH"),
		// Without this, GET /api/admin/version falls through to admin.py's own "UNKNOWN"
		// fallback (confirmed live on the Store-published build: the UI's version badge showed
		// "vUNKNOWN") — the native launcher has no installer-writes-a-.env-file step the way the
		// Podman-based path does, so APP_VERSION/INSTALLER_VERSION were simply never set at all.
		// Version is main.go's own build-time-injected value (-ldflags "-X main.Version=x.y.z"),
		// already used for the WebView2 loading screen — just never threaded through here too.
		"APP_VERSION="+Version,
	)
	cmd.Stdout = out
	cmd.Stderr = out
	if err := cmd.Start(); err != nil {
		out.Close()
		return nil, fmt.Errorf("starting backend: %w", err)
	}
	return cmd, nil
}

// startWorker spawns the bundled PgQueuer worker (issue #83) as a second long-lived child
// process alongside uvicorn — background price sync, ETF holdings refresh, macro indicators,
// country performance, and daily/monthly snapshot computation (see app/tasks/pgq_app.py) never
// ran at all on the native launcher before this, a real functional gap versus the containerized
// version's separate pgq-worker service (compose-prod.yaml). Not unit-testable, same documented
// policy as startBackend.
//
// cmd.Dir must be backendAppDir — pgqueuer's own factory-loading code
// (adapters/cli/factories.py's load_factory) resolves "app.tasks.pgq_app:main" via
// sys.path.insert(0, os.getcwd()), not an --app-dir-style flag the way uvicorn's own CLI
// supports (confirmed against the installed pgqueuer==1.3.2 source — there is no equivalent
// flag). Without an explicit working directory, the launcher's own default CWD has no reason to
// contain the "app" package, and the import would fail.
//
// No PgQueuer schema-install step needed here: alembic/versions/uu44vv55ww66_add_pgqueuer_schema.py
// already embeds the verbatim output of "pgq sql install" for the pinned pgqueuer version, so
// runMigrations (already run on every launch) creates it — confirmed by reading that migration
// directly, not assumed.
func startWorker(home string, pgPort int) (*exec.Cmd, error) {
	if err := os.MkdirAll(logDir(home), 0o755); err != nil {
		return nil, fmt.Errorf("creating log directory: %w", err)
	}
	out, err := os.Create(filepath.Join(logDir(home), "worker.log"))
	if err != nil {
		return nil, fmt.Errorf("creating worker log: %w", err)
	}

	cmd := exec.Command(pythonExePath(home), buildPgqueuerArgs()...)
	cmd.Dir = backendAppDir(home)
	hideWindow(cmd)
	cmd.Env = append(os.Environ(), "DATABASE_URL="+databaseURL(pgPort))
	cmd.Stdout = out
	cmd.Stderr = out
	if err := cmd.Start(); err != nil {
		out.Close()
		return nil, fmt.Errorf("starting worker: %w", err)
	}
	return cmd, nil
}

// stopChildProcess terminates a long-lived child process previously started by startBackend or
// startWorker. Neither uvicorn nor pgqueuer has a pg_ctl-style graceful "stop" command of its
// own to shell out to — killing the process directly is the correct approach here
// (FastAPI/uvicorn's own shutdown handlers still run on SIGTERM on POSIX, but
// Process.Kill sends TerminateProcess on Windows, which does NOT trigger graceful shutdown
// handlers). This is a known, accepted MVP gap: a hard-terminated uvicorn/pgqueuer does not get
// to run its own shutdown event handlers. Acceptable since neither app's shutdown handlers are
// relied upon for data integrity — Postgres's own stopPostgres call, which does perform a real
// graceful shutdown, is what actually matters for data safety, and PgQueuer's own
// heartbeat-based redelivery (see app/tasks/pgq_app.py's docstring) already handles a worker
// dying mid-job without any bespoke cleanup here.
func stopChildProcess(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil {
		return nil
	}
	return cmd.Process.Kill()
}

// waitForHealth polls healthURL until it returns 200, or ctx is done. Timeout-based via the
// caller's context rather than a fixed internal retry count, with a context so the caller can
// show elapsed-time UI feedback while polling.
func waitForHealth(ctx context.Context, backendPort int) error {
	client := &http.Client{Timeout: 2 * time.Second}
	url := healthURL(backendPort)
	for {
		select {
		case <-ctx.Done():
			return fmt.Errorf("backend did not become healthy before the deadline: %w", ctx.Err())
		default:
		}
		resp, err := client.Get(url)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				return nil
			}
		}
		time.Sleep(time.Second)
	}
}
