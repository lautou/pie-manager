package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
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
