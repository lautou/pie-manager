package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

// pgSuperuser is the local Postgres role this app always connects as, with no password —
// matching the #76 poc's --auth=trust. A single-user desktop app listening only on 127.0.0.1
// has no meaningful multi-user access model to protect with a password.
const pgSuperuser = "pie"

// pgDatabaseName matches the database name the real backend's config.py defaults to
// (postgresql+asyncpg://.../pie_db) — initdb only ever creates the "postgres" maintenance
// database, so this app's own database still needs an explicit createdb on first run.
const pgDatabaseName = "pie_db"

// processTimeout bounds every native process this file spawns. Not a workaround for a known
// Go-specific hang (the #76 poc's Start-Process -Wait hang was a PowerShell/.NET-specific
// behavior tied to how that API waits on redirected output streams, not a general Windows
// process-handle-inheritance problem — Go's os/exec, given real *os.File values for
// Stdout/Stderr rather than pipes, does not set up that kind of stream-completion wait, so
// cmd.Wait() only waits on the child's own process handle). This is defensive engineering for a
// real launcher regardless: bound how long we wait on postgres itself failing to become ready,
// not just on a hypothetical hang mechanism.
const processTimeout = 60 * time.Second

func initdbExePath(home string) string   { return filepath.Join(pgBinDir(home), "initdb.exe") }
func pgCtlExePath(home string) string    { return filepath.Join(pgBinDir(home), "pg_ctl.exe") }
func postgresExePath(home string) string { return filepath.Join(pgBinDir(home), "postgres.exe") }
func createdbExePath(home string) string { return filepath.Join(pgBinDir(home), "createdb.exe") }

func buildInitdbArgs(home string) []string {
	return []string{"-D", pgDataDir(home), "-U", pgSuperuser, "--auth=trust"}
}

// buildPgCtlStartArgs binds Postgres to 127.0.0.1 only, on the dynamically selected port -
// never the default 5432 unconditionally (see ports.go).
func buildPgCtlStartArgs(home string, port int) []string {
	return []string{
		"-D", pgDataDir(home),
		"-w", "start",
		"-o", fmt.Sprintf("-p %d -c listen_addresses=127.0.0.1", port),
	}
}

// buildPgCtlStopArgs uses "fast" shutdown mode (disconnect clients, roll back in-progress
// transactions, checkpoint, then exit) — the right mode for a normal graceful window-close, as
// opposed to "immediate" (skips the checkpoint, only appropriate for forced cleanup after an
// error, which is what the #76 poc used since it never needed a clean shutdown guarantee).
func buildPgCtlStopArgs(home string) []string {
	return []string{"-D", pgDataDir(home), "-w", "stop", "-m", "fast"}
}

// buildCreateDbArgs targets the same dynamically-selected port startPostgres just bound to.
func buildCreateDbArgs(port int) []string {
	return []string{"-h", "127.0.0.1", "-p", fmt.Sprintf("%d", port), "-U", pgSuperuser, pgDatabaseName}
}

// runCapturedCommand runs exe with args, bounded by processTimeout, capturing combined
// stdout/stderr to logPath for later inspection. Shared by every native-process call in this
// file so the timeout/logging behavior is applied uniformly.
func runCapturedCommand(exe, logPath string, args ...string) error {
	if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil {
		return fmt.Errorf("creating log directory for %s: %w", filepath.Base(logPath), err)
	}
	out, err := os.Create(logPath)
	if err != nil {
		return fmt.Errorf("creating log file %s: %w", logPath, err)
	}
	defer out.Close()

	ctx, cancel := context.WithTimeout(context.Background(), processTimeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, exe, args...)
	cmd.Stdout = out
	cmd.Stderr = out
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("%s failed (see %s): %w", filepath.Base(exe), logPath, err)
	}
	return nil
}

// runInitdb initializes a fresh Postgres data directory. Only ever called when isFirstRun
// reports true — this and startPostgres/stopPostgres exec real external programs and are not
// unit-testable, matching this project's own documented policy for the existing Podman-based
// installer's system-interaction functions (see CLAUDE.md's "Installer test coverage policy");
// covered instead by the CI install+launch smoke test planned for this MVP.
func runInitdb(home string) error {
	return runCapturedCommand(initdbExePath(home), filepath.Join(logDir(home), "initdb.log"), buildInitdbArgs(home)...)
}

// startPostgres starts (or restarts) the Postgres server bound to 127.0.0.1:port. pg_ctl
// start's own -w flag waits for readiness before returning.
func startPostgres(home string, port int) error {
	return runCapturedCommand(pgCtlExePath(home), filepath.Join(logDir(home), "pgctl-start.log"), buildPgCtlStartArgs(home, port)...)
}

// stopPostgres gracefully stops the server. Called on window close, and defensively before a
// fresh start whenever crash_recovery.go detects a previous session's server may still be
// running.
func stopPostgres(home string) error {
	return runCapturedCommand(pgCtlExePath(home), filepath.Join(logDir(home), "pgctl-stop.log"), buildPgCtlStopArgs(home)...)
}

// createAppDatabase runs createdb against the just-started server. Only ever called on first
// run, once startPostgres has returned successfully - initdb only creates the "postgres"
// maintenance database, not this app's own.
func createAppDatabase(home string, port int) error {
	return runCapturedCommand(createdbExePath(home), filepath.Join(logDir(home), "createdb.log"), buildCreateDbArgs(port)...)
}
