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

// startBackend spawns the bundled uvicorn as a long-lived child process (unlike postgres.go's
// run-to-completion commands) with DATABASE_URL pointing at the given Postgres port. Not
// unit-testable - a real external process spawn, same documented policy as postgres.go's
// process-spawning functions. The caller is responsible for eventually stopping the returned
// *exec.Cmd's process (see stopBackend).
func startBackend(home string, backendPort, pgPort int) (*exec.Cmd, error) {
	if err := os.MkdirAll(logDir(home), 0o755); err != nil {
		return nil, fmt.Errorf("creating log directory: %w", err)
	}
	out, err := os.Create(filepath.Join(logDir(home), "backend.log"))
	if err != nil {
		return nil, fmt.Errorf("creating backend log: %w", err)
	}

	cmd := exec.Command(pythonExePath(home), buildUvicornArgs(home, backendPort)...)
	cmd.Env = append(os.Environ(), "DATABASE_URL="+databaseURL(pgPort))
	cmd.Stdout = out
	cmd.Stderr = out
	if err := cmd.Start(); err != nil {
		out.Close()
		return nil, fmt.Errorf("starting backend: %w", err)
	}
	return cmd, nil
}

// stopBackend terminates a backend process previously started by startBackend. uvicorn has no
// pg_ctl-style graceful "stop" command of its own to shell out to - killing the process directly
// is the correct approach here (FastAPI/uvicorn's own shutdown handlers still run on SIGTERM,
// which Process.Kill sends on Windows via TerminateProcess... actually TerminateProcess does NOT
// trigger graceful shutdown handlers, unlike a real SIGTERM on POSIX. This is a known, accepted
// MVP gap: a hard-terminated uvicorn does not get to run FastAPI's own shutdown event handlers.
// Acceptable for now since this app's shutdown handlers (if any exist) are not relied upon for
// data integrity - Postgres's own stopPostgres call, which does perform a real graceful
// shutdown, is what actually matters for data safety.
func stopBackend(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil {
		return nil
	}
	return cmd.Process.Kill()
}

// waitForHealth polls healthURL until it returns 200, or ctx is done. Timeout-based via the
// caller's context rather than a fixed internal retry count, mirroring today's Podman-based
// installer/launcher/main.go's own /api/admin/version polling loop (Phase 3), generalized here
// with a context so the caller can show elapsed-time UI feedback while polling.
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
