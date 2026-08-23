// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestInitdbExePath(t *testing.T) {
	got := initdbExePath(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "pgsql", "bin", "initdb.exe")
	if got != want {
		t.Errorf("initdbExePath() = %q, want %q", got, want)
	}
}

func TestPgCtlExePath(t *testing.T) {
	got := pgCtlExePath(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "pgsql", "bin", "pg_ctl.exe")
	if got != want {
		t.Errorf("pgCtlExePath() = %q, want %q", got, want)
	}
}

func TestPostgresExePath(t *testing.T) {
	got := postgresExePath(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "pgsql", "bin", "postgres.exe")
	if got != want {
		t.Errorf("postgresExePath() = %q, want %q", got, want)
	}
}

func TestBuildInitdbArgs(t *testing.T) {
	args := buildInitdbArgs(`C:\Users\pie`)
	want := []string{"-D", filepath.Join(`C:\Users\pie`, "PieManager", "pgdata"), "-U", "pie", "--auth=trust"}
	if len(args) != len(want) {
		t.Fatalf("buildInitdbArgs() = %v, want %v", args, want)
	}
	for i := range want {
		if args[i] != want[i] {
			t.Errorf("buildInitdbArgs()[%d] = %q, want %q", i, args[i], want[i])
		}
	}
}

func TestBuildPostgresArgs(t *testing.T) {
	args := buildPostgresArgs(`C:\Users\pie`, 15432)
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "-p 15432") {
		t.Errorf("expected port 15432 in args, got %v", args)
	}
	if !strings.Contains(joined, "listen_addresses=127.0.0.1") {
		t.Errorf("expected listen_addresses=127.0.0.1 in args, got %v", args)
	}
	if !strings.Contains(joined, pgDataDir(`C:\Users\pie`)) {
		t.Errorf("expected pgdata path in args, got %v", args)
	}
}

func TestBuildPgCtlStopArgs(t *testing.T) {
	args := buildPgCtlStopArgs(`C:\Users\pie`)
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "-m fast") {
		t.Errorf("expected fast shutdown mode in args, got %v", args)
	}
	if !strings.Contains(joined, pgDataDir(`C:\Users\pie`)) {
		t.Errorf("expected pgdata path in args, got %v", args)
	}
}

func TestBuildPgCtlStopImmediateArgs(t *testing.T) {
	args := buildPgCtlStopImmediateArgs(`C:\Users\pie`)
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "-m immediate") {
		t.Errorf("expected immediate shutdown mode in args, got %v", args)
	}
	if !strings.Contains(joined, pgDataDir(`C:\Users\pie`)) {
		t.Errorf("expected pgdata path in args, got %v", args)
	}
}

func TestCreatedbExePath(t *testing.T) {
	got := createdbExePath(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "pgsql", "bin", "createdb.exe")
	if got != want {
		t.Errorf("createdbExePath() = %q, want %q", got, want)
	}
}

func TestBuildCreateDbArgs(t *testing.T) {
	args := buildCreateDbArgs(15432)
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "-p 15432") {
		t.Errorf("expected port 15432 in args, got %v", args)
	}
	if !strings.Contains(joined, pgDatabaseName) {
		t.Errorf("expected database name %q in args, got %v", pgDatabaseName, args)
	}
	if !strings.Contains(joined, pgSuperuser) {
		t.Errorf("expected superuser %q in args, got %v", pgSuperuser, args)
	}
}

func TestRunCapturedCommand_Success(t *testing.T) {
	home := t.TempDir()
	logPath := filepath.Join(home, "logs", "test.log")

	exe := "/bin/echo"
	if _, err := os.Stat(exe); err != nil {
		t.Skip("/bin/echo not available on this platform")
	}
	if err := runCapturedCommand(exe, logPath, "hello"); err != nil {
		t.Fatalf("runCapturedCommand failed: %v", err)
	}
	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("expected log file to exist: %v", err)
	}
	if !strings.Contains(string(content), "hello") {
		t.Errorf("expected log to contain command output, got %q", string(content))
	}
}

func TestRunCapturedCommand_NonZeroExit(t *testing.T) {
	home := t.TempDir()
	logPath := filepath.Join(home, "logs", "test.log")

	exe := "/bin/false"
	if _, err := os.Stat(exe); err != nil {
		t.Skip("/bin/false not available on this platform")
	}
	if err := runCapturedCommand(exe, logPath); err == nil {
		t.Error("expected an error for a non-zero exit command")
	}
}

// TestRunCapturedCommand_ErrorIncludesLogContent guards against issue #82's second
// certification failure: a bare "python.exe failed (see alembic.log): exit status 1" told the
// on-screen error nothing, and Microsoft Store certification never provides log file access —
// the real failure has to already be inside the returned error, not just its log path.
func TestRunCapturedCommand_ErrorIncludesLogContent(t *testing.T) {
	shExe := "/bin/sh"
	if _, err := os.Stat(shExe); err != nil {
		t.Skip("/bin/sh not available on this platform")
	}
	home := t.TempDir()
	logPath := filepath.Join(home, "logs", "test.log")

	err := runCapturedCommand(shExe, logPath, "-c", "echo boom-diagnostic-marker; exit 1")
	if err == nil {
		t.Fatal("expected an error for a non-zero exit command")
	}
	if !strings.Contains(err.Error(), "boom-diagnostic-marker") {
		t.Errorf("expected the returned error to include the command's own log output, got %q", err.Error())
	}
}

func TestRunCapturedCommand_MissingExecutable(t *testing.T) {
	home := t.TempDir()
	logPath := filepath.Join(home, "logs", "test.log")

	if err := runCapturedCommand(filepath.Join(home, "does-not-exist.exe"), logPath); err == nil {
		t.Error("expected an error for a missing executable")
	}
}

func TestRunCapturedCommandIn_UsesWorkingDirectoryAndEnv(t *testing.T) {
	home := t.TempDir()
	logPath := filepath.Join(home, "logs", "test.log")

	shExe := "/bin/sh"
	if _, err := os.Stat(shExe); err != nil {
		t.Skip("/bin/sh not available on this platform")
	}
	// Prints the CWD and an env var set via extraEnv - proves both are actually applied, not
	// just accepted as parameters.
	if err := runCapturedCommandIn(home, []string{"MY_TEST_VAR=hello"}, processTimeout, shExe, logPath, "-c", "pwd && echo $MY_TEST_VAR"); err != nil {
		t.Fatalf("runCapturedCommandIn failed: %v", err)
	}
	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("expected log file to exist: %v", err)
	}
	got := string(content)
	if !strings.Contains(got, home) {
		t.Errorf("expected log to show working directory %q, got %q", home, got)
	}
	if !strings.Contains(got, "hello") {
		t.Errorf("expected log to show env var value, got %q", got)
	}
}

func TestRunCapturedCommand_ErrorWhenLogPathIsDirectory(t *testing.T) {
	home := t.TempDir()
	// logPath itself exists as a directory — MkdirAll(Dir(logPath)) succeeds (its parent),
	// but os.Create(logPath) fails because you cannot open a directory for writing.
	logPath := filepath.Join(home, "logs", "test.log")
	if err := os.MkdirAll(logPath, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := runCapturedCommand("/bin/echo", logPath, "hi"); err == nil {
		t.Error("expected an error when logPath itself is a directory")
	}
}

// TestRunCapturedCommandIn_RespectsPerCallTimeout guards against issue #82's certification
// failure regressing: runMigrations was killed at 60s because the timeout used to be a single
// package-level constant baked into runCapturedCommandIn, shared by every caller regardless of
// how long its command legitimately needs. Proves the timeout is a real per-call parameter, not
// a fixed value, by giving the same long-running command two different budgets and observing
// two different outcomes.
func TestRunCapturedCommandIn_RespectsPerCallTimeout(t *testing.T) {
	sleepExe := "/bin/sleep"
	if _, err := os.Stat(sleepExe); err != nil {
		t.Skip("/bin/sleep not available on this platform")
	}

	home := t.TempDir()
	shortTimeoutLog := filepath.Join(home, "logs", "short.log")
	start := time.Now()
	err := runCapturedCommandIn("", nil, 200*time.Millisecond, sleepExe, shortTimeoutLog, "5")
	elapsed := time.Since(start)
	if err == nil {
		t.Error("expected a timeout error for a command exceeding its short per-call timeout")
	}
	if elapsed >= 5*time.Second {
		t.Errorf("expected the short timeout to kill the process well before its 5s sleep completed, took %v", elapsed)
	}

	generousTimeoutLog := filepath.Join(home, "logs", "generous.log")
	if err := runCapturedCommandIn("", nil, 5*time.Second, sleepExe, generousTimeoutLog, "0.1"); err != nil {
		t.Errorf("expected a generous timeout to let a quick command finish normally, got %v", err)
	}
}

func TestRunCapturedCommand_ErrorWhenLogDirBlockedByFile(t *testing.T) {
	home := t.TempDir()
	blocker := filepath.Join(home, "blocked")
	if err := os.WriteFile(blocker, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	logPath := filepath.Join(blocker, "test.log")

	if err := runCapturedCommand("/bin/echo", logPath, "hi"); err == nil {
		t.Error("expected an error when the log directory path is blocked by an existing file")
	}
}

func TestTailLogFile_ReturnsFullContentWhenUnderLimit(t *testing.T) {
	home := t.TempDir()
	logPath := filepath.Join(home, "test.log")
	if err := os.WriteFile(logPath, []byte("short content"), 0o644); err != nil {
		t.Fatal(err)
	}
	got := tailLogFile(logPath, 4000)
	if got != "short content" {
		t.Errorf("tailLogFile() = %q, want %q", got, "short content")
	}
}

func TestTailLogFile_TruncatesOversizedContent(t *testing.T) {
	home := t.TempDir()
	logPath := filepath.Join(home, "test.log")
	content := strings.Repeat("a", 100) + "TAIL_MARKER"
	if err := os.WriteFile(logPath, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	got := tailLogFile(logPath, 20)
	if !strings.HasPrefix(got, "...(truncated)...\n") {
		t.Errorf("expected truncated output to start with the truncation marker, got %q", got)
	}
	if !strings.HasSuffix(got, "TAIL_MARKER") {
		t.Errorf("expected truncated output to keep the tail end of the content, got %q", got)
	}
}

func TestTailLogFile_MissingFile(t *testing.T) {
	got := tailLogFile("/does/not/exist.log", 100)
	if !strings.Contains(got, "could not read") {
		t.Errorf("expected a placeholder message for a missing file, got %q", got)
	}
}

// writeFakeExecutable creates an executable shell script at path - a stand-in for postgres.exe
// in tests that need a real process exec.Command can start and later observe exiting (or not),
// without a real Postgres binary. postgresExePath(home) is a pure function of home, so writing
// directly to that computed path lets startPostgres itself run unmodified against it.
func writeFakeExecutable(t *testing.T, path, script string) {
	t.Helper()
	if _, err := os.Stat("/bin/sh"); err != nil {
		t.Skip("/bin/sh not available on this platform")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+script+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
}

func TestStartPostgres_Success(t *testing.T) {
	home := t.TempDir()
	writeFakeExecutable(t, postgresExePath(home), "sleep 30")

	cmd, err := startPostgres(home, 15432)
	if err != nil {
		t.Fatalf("startPostgres failed: %v", err)
	}
	defer func() {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
	}()
	if cmd.Process == nil {
		t.Fatal("expected a started process")
	}
	if _, err := os.Stat(postgresLogPath(home)); err != nil {
		t.Errorf("expected the postgres log file to exist: %v", err)
	}
}

func TestStartPostgres_MissingExecutable(t *testing.T) {
	home := t.TempDir()
	if _, err := startPostgres(home, 15432); err == nil {
		t.Error("expected an error when postgres.exe does not exist")
	}
}

func TestStartPostgres_ErrorWhenLogDirBlockedByFile(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(dataDir(home), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(logDir(home), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := startPostgres(home, 15432); err == nil {
		t.Error("expected an error when the log directory path is blocked by an existing file")
	}
}

func TestStartPostgres_ErrorWhenLogPathIsDirectory(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(postgresLogPath(home), 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := startPostgres(home, 15432); err == nil {
		t.Error("expected an error when the postgres log path is itself a directory")
	}
}

func TestPgIsReadyExePath(t *testing.T) {
	got := pgIsReadyExePath(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "pgsql", "bin", "pg_isready.exe")
	if got != want {
		t.Errorf("pgIsReadyExePath() = %q, want %q", got, want)
	}
}

func TestBuildPgIsReadyArgs(t *testing.T) {
	args := buildPgIsReadyArgs(15432)
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "-p 15432") {
		t.Errorf("expected port 15432 in args, got %v", args)
	}
	if !strings.Contains(joined, "-d postgres") {
		t.Errorf("expected the maintenance database 'postgres' in args, got %v", args)
	}
	if !strings.Contains(joined, pgSuperuser) {
		t.Errorf("expected superuser %q in args, got %v", pgSuperuser, args)
	}
}

func TestPostgresAcceptingConnections_True(t *testing.T) {
	home := t.TempDir()
	writeFakeExecutable(t, pgIsReadyExePath(home), "exit 0")
	if !postgresAcceptingConnections(home, 15432) {
		t.Error("expected true when pg_isready exits 0")
	}
}

func TestPostgresAcceptingConnections_False(t *testing.T) {
	home := t.TempDir()
	writeFakeExecutable(t, pgIsReadyExePath(home), "exit 1")
	if postgresAcceptingConnections(home, 15432) {
		t.Error("expected false when pg_isready exits non-zero")
	}
}

// TestWaitForPostgresReady_SucceedsWhenPgIsReadyReportsReady guards against issue #83's live
// functional-pass finding: a bare TCP dial succeeds before Postgres can actually complete a real
// connection handshake, which broke runMigrations with "connection was closed in the middle of
// operation". Using a fake pg_isready removes the race entirely - readiness is deterministic
// (its exit code), not timing-dependent on an actual server.
func TestWaitForPostgresReady_SucceedsWhenPgIsReadyReportsReady(t *testing.T) {
	sleepExe := "/bin/sleep"
	if _, err := os.Stat(sleepExe); err != nil {
		t.Skip("/bin/sleep not available on this platform")
	}
	home := t.TempDir()
	writeFakeExecutable(t, pgIsReadyExePath(home), "exit 0")

	cmd := exec.Command(sleepExe, "30")
	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start test process: %v", err)
	}
	defer func() {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
	}()

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := waitForPostgresReady(ctx, cmd, home, 15432); err != nil {
		t.Errorf("expected success, got %v", err)
	}
}

func TestWaitForPostgresReady_TimesOutWhenNeverReady(t *testing.T) {
	sleepExe := "/bin/sleep"
	if _, err := os.Stat(sleepExe); err != nil {
		t.Skip("/bin/sleep not available on this platform")
	}
	home := t.TempDir()
	writeFakeExecutable(t, pgIsReadyExePath(home), "exit 1")

	cmd := exec.Command(sleepExe, "30")
	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start test process: %v", err)
	}
	defer func() {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
	}()

	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	// The process stays alive the whole time (still sleeping) but pg_isready always reports
	// not-ready, so this exercises the ctx-deadline branch specifically, not the early-exit
	// branch below.
	if err := waitForPostgresReady(ctx, cmd, home, 15432); err == nil {
		t.Error("expected a timeout error when pg_isready never reports ready")
	}
}

func TestWaitForPostgresReady_ReturnsErrorWhenProcessExitsEarly(t *testing.T) {
	shExe := "/bin/sh"
	if _, err := os.Stat(shExe); err != nil {
		t.Skip("/bin/sh not available on this platform")
	}
	home := t.TempDir()
	if err := os.MkdirAll(filepath.Dir(postgresLogPath(home)), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(postgresLogPath(home), []byte("boom-diagnostic-marker"), 0o644); err != nil {
		t.Fatal(err)
	}

	cmd := exec.Command(shExe, "-c", "exit 1")
	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start test process: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	// Port 1 - nothing listens there, so the only way this returns before the 5s deadline is via
	// the early-exit branch, proving it's real and not just theoretically reachable.
	err := waitForPostgresReady(ctx, cmd, home, 1)
	if err == nil {
		t.Fatal("expected an error when the process exits before becoming ready")
	}
	if !strings.Contains(err.Error(), "boom-diagnostic-marker") {
		t.Errorf("expected the error to include the process's own log content, got %q", err.Error())
	}
}
