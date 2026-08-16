package main

import (
	"os"
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

func TestBuildPgCtlStartArgs(t *testing.T) {
	args := buildPgCtlStartArgs(`C:\Users\pie`, 15432)
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
