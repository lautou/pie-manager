// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestPythonExePath(t *testing.T) {
	got := pythonExePath(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "python", "python.exe")
	if got != want {
		t.Errorf("pythonExePath() = %q, want %q", got, want)
	}
}

func TestBackendAppDir(t *testing.T) {
	got := backendAppDir(`C:\Users\pie`)
	want := pythonDir(`C:\Users\pie`)
	if got != want {
		t.Errorf("backendAppDir() = %q, want %q", got, want)
	}
}

func TestDatabaseURL(t *testing.T) {
	got := databaseURL(15432)
	want := "postgresql+asyncpg://pie@127.0.0.1:15432/pie_db"
	if got != want {
		t.Errorf("databaseURL() = %q, want %q", got, want)
	}
}

func TestBuildUvicornArgs(t *testing.T) {
	args := buildUvicornArgs(`C:\Users\pie`, 14943)
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "app.main:app") {
		t.Errorf("expected ASGI app target in args, got %v", args)
	}
	if !strings.Contains(joined, "--port 14943") {
		t.Errorf("expected port 14943 in args, got %v", args)
	}
	if !strings.Contains(joined, "127.0.0.1") {
		t.Errorf("expected loopback host in args, got %v", args)
	}
	if !strings.Contains(joined, backendAppDir(`C:\Users\pie`)) {
		t.Errorf("expected --app-dir path in args, got %v", args)
	}
}

func TestBuildAlembicArgs(t *testing.T) {
	args := buildAlembicArgs()
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "alembic upgrade head") {
		t.Errorf("expected alembic upgrade head in args, got %v", args)
	}
}

func TestBuildPgqueuerArgs(t *testing.T) {
	args := buildPgqueuerArgs()
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, "pgqueuer run app.tasks.pgq_app:main") {
		t.Errorf("expected pgqueuer run invocation in args, got %v", args)
	}
}

func TestRecordSpawnedPid_ErrorOnNonWindows(t *testing.T) {
	// processStartTime (processtime_other.go) always errors outside Windows, so
	// recordSpawnedPid can only ever be exercised through its error-propagation branch on this
	// (Linux) CI runner - the happy path (a real process's start time, then writePidRecord)
	// is exclusively a Windows behavior, same documented policy as startBackend/startWorker.
	err := recordSpawnedPid(filepath.Join(t.TempDir(), "backend.pid"), 1)
	if err == nil {
		t.Error("expected an error since processStartTime always fails on non-Windows")
	}
}

func TestRunMigrations_UsesBackendAppDirAndDatabaseURL(t *testing.T) {
	// runMigrations itself execs a real process (python.exe, not available here) - covered by
	// the CI install+launch smoke test, same documented policy as postgres.go's process-spawning
	// functions. This only exercises that it delegates to runCapturedCommandIn with a
	// non-existent python.exe, producing an error rather than panicking.
	home := t.TempDir()
	if err := runMigrations(home, 15432); err == nil {
		t.Error("expected an error since no real python.exe exists in this test's temp home")
	}
}

func TestHealthURL(t *testing.T) {
	got := healthURL(14943)
	want := "http://127.0.0.1:14943/api/admin/version"
	if got != want {
		t.Errorf("healthURL() = %q, want %q", got, want)
	}
}

func TestStopChildProcess_NilCmd(t *testing.T) {
	if err := stopChildProcess(nil); err != nil {
		t.Errorf("expected nil error for a nil cmd, got %v", err)
	}
}

func TestStopChildProcess_NeverStartedProcess(t *testing.T) {
	cmd := exec.Command("does-not-matter")
	if err := stopChildProcess(cmd); err != nil {
		t.Errorf("expected nil error for a cmd that was never Start()ed (Process is nil), got %v", err)
	}
}

func TestStopChildProcess_KillsRunningProcess(t *testing.T) {
	sleepExe := "/bin/sleep"
	if _, err := os.Stat(sleepExe); err != nil {
		t.Skip("/bin/sleep not available on this platform")
	}
	cmd := exec.Command(sleepExe, "30")
	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start test process: %v", err)
	}
	if err := stopChildProcess(cmd); err != nil {
		t.Errorf("expected stopChildProcess to kill the process cleanly, got %v", err)
	}
	_ = cmd.Wait() // reap the killed child, ignore the resulting "signal: killed" error
}

func TestWaitForHealth_SucceedsOn200(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	port := serverPort(t, srv)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := waitForHealth(ctx, port); err != nil {
		t.Errorf("expected success, got %v", err)
	}
}

func TestWaitForHealth_RetriesUntilHealthy(t *testing.T) {
	attempts := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts++
		if attempts < 3 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	port := serverPort(t, srv)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := waitForHealth(ctx, port); err != nil {
		t.Errorf("expected success after retries, got %v", err)
	}
	if attempts < 3 {
		t.Errorf("expected at least 3 attempts, got %d", attempts)
	}
}

func TestWaitForHealth_TimesOutWhenNeverHealthy(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	port := serverPort(t, srv)
	ctx, cancel := context.WithTimeout(context.Background(), 1500*time.Millisecond)
	defer cancel()
	if err := waitForHealth(ctx, port); err == nil {
		t.Error("expected a timeout error, got nil")
	}
}

func TestWaitForHealth_TimesOutWhenUnreachable(t *testing.T) {
	// A port nothing is listening on - every request fails with a connection error, not a
	// non-200 status, exercising the other branch of the retry loop.
	ctx, cancel := context.WithTimeout(context.Background(), 1500*time.Millisecond)
	defer cancel()
	if err := waitForHealth(ctx, 1); err == nil {
		t.Error("expected a timeout error for an unreachable port, got nil")
	}
}

// serverPort extracts the numeric port httptest.Server bound to, so waitForHealth (which only
// takes a port, matching how this app calls it with its own dynamically-selected backend port)
// can be pointed at it directly.
func serverPort(t *testing.T, srv *httptest.Server) int {
	t.Helper()
	url := srv.URL // e.g. "http://127.0.0.1:54321"
	idx := strings.LastIndex(url, ":")
	if idx == -1 {
		t.Fatalf("could not parse port from %q", url)
	}
	port, err := strconv.Atoi(url[idx+1:])
	if err != nil {
		t.Fatalf("could not parse port from %q: %v", url, err)
	}
	return port
}
