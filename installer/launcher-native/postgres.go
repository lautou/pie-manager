// SPDX-License-Identifier: AGPL-3.0-or-later

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

// processTimeout bounds every short-lived native Postgres process this file spawns (initdb,
// pg_ctl stop, createdb), and separately doubles as orchestrator.go's budget for
// waitForPostgresReady now that startPostgres bypasses "pg_ctl start" (see startPostgres's own
// comment for why) — reused rather than a dedicated constant since both represent the same
// underlying concern: how long a locked-down environment might delay Postgres becoming usable.
// Not a workaround for a known Go-specific hang (the #76 poc's
// Start-Process -Wait hang was a PowerShell/.NET-specific behavior tied to how that API waits on
// redirected output streams, not a general Windows process-handle-inheritance problem — Go's
// os/exec, given real *os.File values for Stdout/Stderr rather than pipes, does not set up that
// kind of stream-completion wait, so cmd.Wait() only waits on the child's own process handle).
// This is defensive engineering for a real launcher regardless: bound how long we wait on
// postgres itself failing to become ready, not just on a hypothetical hang mechanism.
//
// Deliberately NOT used for backend.go's runMigrations — see migrationTimeout there for why a
// first-run Alembic chain needs a much longer, separate budget (issue #82 certification
// failure: this constant used to be shared with runMigrations via the same
// runCapturedCommandIn call, and killed a slow-but-legitimate first-run migration mid-flight).
const processTimeout = 60 * time.Second

func initdbExePath(home string) string    { return filepath.Join(pgBinDir(home), "initdb.exe") }
func pgCtlExePath(home string) string     { return filepath.Join(pgBinDir(home), "pg_ctl.exe") }
func postgresExePath(home string) string  { return filepath.Join(pgBinDir(home), "postgres.exe") }
func createdbExePath(home string) string  { return filepath.Join(pgBinDir(home), "createdb.exe") }
func pgIsReadyExePath(home string) string { return filepath.Join(pgBinDir(home), "pg_isready.exe") }

func buildInitdbArgs(home string) []string {
	return []string{"-D", pgDataDir(home), "-U", pgSuperuser, "--auth=trust"}
}

// buildPostgresArgs binds Postgres to 127.0.0.1 only, on the dynamically selected port - never
// the default 5432 unconditionally (see ports.go). Used to launch postgres.exe directly (see
// startPostgres) rather than via "pg_ctl start" - pg_ctl accepts the same two settings through
// its own "-o" passthrough flag, but direct invocation takes them as top-level postgres.exe
// arguments instead.
func buildPostgresArgs(home string, port int) []string {
	return []string{
		"-D", pgDataDir(home),
		"-p", fmt.Sprintf("%d", port),
		"-c", "listen_addresses=127.0.0.1",
	}
}

// buildPgCtlStopArgs uses "fast" shutdown mode (disconnect clients, roll back in-progress
// transactions, checkpoint, then exit) — the right mode for a normal graceful window-close, as
// opposed to "immediate" (skips the checkpoint, only appropriate for forced cleanup after an
// error, which is what the #76 poc used since it never needed a clean shutdown guarantee).
func buildPgCtlStopArgs(home string) []string {
	return []string{"-D", pgDataDir(home), "-w", "stop", "-m", "fast"}
}

// buildPgCtlStopImmediateArgs uses "immediate" mode - see recoverOrphanedPostgres
// (crash_recovery.go), the only caller: cleaning up a previous session's orphaned postmaster,
// where there's no live connection to gracefully disconnect and Postgres's own WAL-based crash
// recovery already handles data-integrity concerns on its next start regardless.
func buildPgCtlStopImmediateArgs(home string) []string {
	return []string{"-D", pgDataDir(home), "-w", "stop", "-m", "immediate"}
}

// buildCreateDbArgs targets the same dynamically-selected port startPostgres just bound to.
func buildCreateDbArgs(port int) []string {
	return []string{"-h", "127.0.0.1", "-p", fmt.Sprintf("%d", port), "-U", pgSuperuser, pgDatabaseName}
}

// buildPgIsReadyArgs targets the "postgres" maintenance database explicitly, not pgDatabaseName —
// pg_isready must succeed even on the very first run, before createAppDatabase has created
// pie_db, and "postgres" always exists post-initdb.
func buildPgIsReadyArgs(port int) []string {
	return []string{"-h", "127.0.0.1", "-p", fmt.Sprintf("%d", port), "-U", pgSuperuser, "-d", "postgres"}
}

// runCapturedCommand runs exe with args, bounded by processTimeout, capturing combined
// stdout/stderr to logPath for later inspection. Shared by every short-lived, run-to-completion
// Postgres process call in this file. Not used for startBackend, which spawns a long-lived
// server rather than running a command to completion.
func runCapturedCommand(exe, logPath string, args ...string) error {
	return runCapturedCommandIn("", nil, processTimeout, exe, logPath, args...)
}

// runCapturedCommandIn is runCapturedCommand with an optional working directory, extra
// environment variables, and an explicit timeout - used by backend.go's runMigrations, which
// needs all three (alembic.ini's relative script_location requires the right working directory;
// DATABASE_URL must point at the dynamically-selected Postgres port; migrationTimeout must be
// far longer than the quick Postgres commands' processTimeout - see migrationTimeout's own
// comment for why).
func runCapturedCommandIn(dir string, extraEnv []string, timeout time.Duration, exe, logPath string, args ...string) error {
	if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil {
		return fmt.Errorf("creating log directory for %s: %w", filepath.Base(logPath), err)
	}
	out, err := os.Create(logPath)
	if err != nil {
		return fmt.Errorf("creating log file %s: %w", logPath, err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, exe, args...)
	hideWindow(cmd)
	cmd.Dir = dir
	if len(extraEnv) > 0 {
		cmd.Env = append(os.Environ(), extraEnv...)
	}
	cmd.Stdout = out
	cmd.Stderr = out
	runErr := cmd.Run()
	out.Close()
	if runErr != nil {
		// Include the log's own content directly in the returned error, not just its path.
		// Microsoft Store certification reports never provide log file access (confirmed live,
		// issue #82: two rejections in a row, neither with a usable "Supporting files" ZIP) —
		// main.go's on-screen fatal error is the ONLY diagnostic surface a reviewer's own
		// screenshot can capture, so the real failure needs to already be in that message.
		return fmt.Errorf("%s failed: %w\n\n%s", filepath.Base(exe), runErr, tailLogFile(logPath, maxErrorLogTail))
	}
	return nil
}

// maxErrorLogTail caps how much of a failed command's log is surfaced in the on-screen error —
// generous enough for a full Python traceback (typically well under this), small enough to
// stay readable in a fixed-size window.
const maxErrorLogTail = 4000

// tailLogFile returns up to maxBytes of logPath's tail, or a placeholder if it can't be read.
// Reads the file back after the writer has already closed it (see runCapturedCommandIn), so
// there's no cross-platform concern about reading a still-open file.
func tailLogFile(logPath string, maxBytes int) string {
	data, err := os.ReadFile(logPath)
	if err != nil {
		return fmt.Sprintf("(could not read %s: %v)", logPath, err)
	}
	if len(data) > maxBytes {
		return "...(truncated)...\n" + string(data[len(data)-maxBytes:])
	}
	return string(data)
}

// runInitdb initializes a fresh Postgres data directory. Only ever called when isFirstRun
// reports true — this and startPostgres/stopPostgres exec real external programs and are not
// unit-testable, matching this project's own documented policy for the existing Podman-based
// installer's system-interaction functions (see CLAUDE.md's "Installer test coverage policy");
// covered instead by the CI install+launch smoke test planned for this MVP.
func runInitdb(home string) error {
	return runCapturedCommand(initdbExePath(home), filepath.Join(logDir(home), "initdb.log"), buildInitdbArgs(home)...)
}

// postgresLogPath is postgres.exe's own direct stdout/stderr capture - distinct from
// pgctl-stop.log, which is pg_ctl's own output for the (still pg_ctl-based) stop path.
func postgresLogPath(home string) string { return filepath.Join(logDir(home), "postgres.log") }

// startPostgres launches postgres.exe directly, bypassing "pg_ctl start" - not unit-testable
// (a real external process spawn), same documented policy as startBackend/runInitdb. Not
// idempotent restart-safe on its own: unlike pg_ctl -w, there's no built-in readiness wait here,
// which is why waitForPostgresReady is a separate, explicit step the caller must run afterward.
//
// Why not pg_ctl start: pg_ctl internally spawns postgres.exe via its own Windows CreateProcess
// call, with its own new console - confirmed live (issue #82's Store verification): hiding
// pg_ctl.exe's own window via hideWindow() had zero effect on postgres.exe's separately-created
// console, which stayed visible for the server's entire lifetime. Spawning postgres.exe
// ourselves puts it under our own exec.Cmd, where hideWindow() actually applies. Registering
// Postgres as a real Windows service was considered as an alternative fix and rejected: it
// requires admin privileges to register (Windows SCM's CreateService, and PostgreSQL's own
// "pg_ctl register" wrapper around it, both require elevation - confirmed, no unprivileged
// exception exists), which conflicts with this launcher's hard no-elevation design constraint.
func startPostgres(home string, port int) (*exec.Cmd, error) {
	if err := os.MkdirAll(logDir(home), 0o755); err != nil {
		return nil, fmt.Errorf("creating log directory: %w", err)
	}
	out, err := os.Create(postgresLogPath(home))
	if err != nil {
		return nil, fmt.Errorf("creating postgres log: %w", err)
	}
	cmd := exec.Command(postgresExePath(home), buildPostgresArgs(home, port)...)
	hideWindow(cmd)
	cmd.Stdout = out
	cmd.Stderr = out
	if err := cmd.Start(); err != nil {
		out.Close()
		return nil, fmt.Errorf("starting postgres: %w", err)
	}
	return cmd, nil
}

// postgresReadyPollInterval bounds how often waitForPostgresReady retries pg_isready - short
// enough that a fast-starting Postgres isn't held up waiting on the previous poll's sleep, long
// enough not to busy-loop or flood the log directory with pg_isready's own short-lived spawns.
const postgresReadyPollInterval = 100 * time.Millisecond

// postgresAcceptingConnections runs the bundled pg_isready against 127.0.0.1:port, reporting
// true only on exit code 0 ("the server is accepting connections normally" per pg_isready's own
// documented exit codes - 1 means rejecting connections, e.g. still starting up, 2 means no
// response at all). Deliberately not a raw TCP dial: issue #83's live functional-pass testing
// found a real race - a bare net.Dial succeeds as soon as postgres.exe's listener socket is
// bound, which is measurably earlier than the server can actually complete a real connection
// handshake, and runMigrations's asyncpg connection attempt failed with
// "ConnectionDoesNotExistError: connection was closed in the middle of operation" as a direct
// result. pg_isready performs a real, lightweight libpq-level connection attempt - the same
// class of check pg_ctl's own "-w" flag relies on internally - so it cannot report ready before
// Postgres genuinely can handle one.
func postgresAcceptingConnections(home string, port int) bool {
	cmd := exec.Command(pgIsReadyExePath(home), buildPgIsReadyArgs(port)...)
	hideWindow(cmd)
	return cmd.Run() == nil
}

// waitForPostgresReady polls until Postgres genuinely accepts connections on 127.0.0.1:port
// (see postgresAcceptingConnections), cmd's process exits early (a real startup failure - reads
// its own log content back into the error, same #82-driven philosophy as runCapturedCommandIn:
// Microsoft Store certification screenshots are the only diagnostic surface available, so the
// real failure has to already be in the message), or ctx's deadline passes. Replaces
// "pg_ctl start"'s own built-in "-w" readiness wait now that startPostgres bypasses pg_ctl (see
// startPostgres's own comment for why).
//
// Detects early exit via cmd.Wait() in a background goroutine, not crash_recovery.go's
// isPidRunning - isPidRunning's own doc comment already notes it's only a real liveness check on
// Windows (os.FindProcess always succeeds on POSIX regardless of whether the pid exists), which
// would make this function's early-exit path untestable on Linux for the wrong reason (a
// platform quirk of a helper picked for convenience, not because cmd.Wait() itself is
// platform-limited - it isn't). cmd.Wait() is safe to call exactly once per *exec.Cmd; nothing
// else ever waits on postgresCmd (stopPostgres shuts it down via a separate "pg_ctl stop"
// signal, not this handle), so this is the only consumer.
func waitForPostgresReady(ctx context.Context, cmd *exec.Cmd, home string, port int) error {
	exited := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(exited)
	}()

	for {
		select {
		case <-ctx.Done():
			return fmt.Errorf("postgres did not become ready before the deadline: %w\n\n%s",
				ctx.Err(), tailLogFile(postgresLogPath(home), maxErrorLogTail))
		case <-exited:
			return fmt.Errorf("postgres exited unexpectedly before becoming ready\n\n%s",
				tailLogFile(postgresLogPath(home), maxErrorLogTail))
		default:
		}

		if postgresAcceptingConnections(home, port) {
			return nil
		}

		time.Sleep(postgresReadyPollInterval)
	}
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
