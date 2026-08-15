package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDataDir(t *testing.T) {
	got := dataDir(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager")
	if got != want {
		t.Errorf("dataDir() = %q, want %q", got, want)
	}
}

func TestPgDataDir(t *testing.T) {
	got := pgDataDir(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "pgdata")
	if got != want {
		t.Errorf("pgDataDir() = %q, want %q", got, want)
	}
}

func TestPgBinDir(t *testing.T) {
	got := pgBinDir(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "pgsql", "bin")
	if got != want {
		t.Errorf("pgBinDir() = %q, want %q", got, want)
	}
}

func TestPythonDir(t *testing.T) {
	got := pythonDir(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "python")
	if got != want {
		t.Errorf("pythonDir() = %q, want %q", got, want)
	}
}

func TestLogDir(t *testing.T) {
	got := logDir(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "logs")
	if got != want {
		t.Errorf("logDir() = %q, want %q", got, want)
	}
}

func TestPgVersionMarkerPath(t *testing.T) {
	got := pgVersionMarkerPath(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "pgdata", "PG_VERSION")
	if got != want {
		t.Errorf("pgVersionMarkerPath() = %q, want %q", got, want)
	}
}

func TestPostmasterPidPath(t *testing.T) {
	got := postmasterPidPath(`C:\Users\pie`)
	want := filepath.Join(`C:\Users\pie`, "PieManager", "pgdata", "postmaster.pid")
	if got != want {
		t.Errorf("postmasterPidPath() = %q, want %q", got, want)
	}
}

func TestIsFirstRun_TrueWhenNoDataDir(t *testing.T) {
	home := t.TempDir()
	if !isFirstRun(home) {
		t.Error("expected isFirstRun to be true for a fresh home with no pgdata at all")
	}
}

func TestIsFirstRun_TrueWhenPgDataExistsButEmpty(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(pgDataDir(home), 0o755); err != nil {
		t.Fatal(err)
	}
	if !isFirstRun(home) {
		t.Error("expected isFirstRun to be true for an existing-but-uninitialized pgdata (partial/interrupted first run)")
	}
}

func TestIsFirstRun_FalseWhenPgVersionMarkerPresent(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(pgDataDir(home), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(pgVersionMarkerPath(home), []byte("16\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if isFirstRun(home) {
		t.Error("expected isFirstRun to be false once PG_VERSION exists")
	}
}

func TestEnsureDataDirs_CreatesAll(t *testing.T) {
	home := t.TempDir()
	if err := ensureDataDirs(home); err != nil {
		t.Fatalf("ensureDataDirs failed: %v", err)
	}
	for _, d := range []string{dataDir(home), pgDataDir(home), pgBinDir(home), pythonDir(home), logDir(home)} {
		info, err := os.Stat(d)
		if err != nil {
			t.Errorf("expected %s to exist: %v", d, err)
			continue
		}
		if !info.IsDir() {
			t.Errorf("expected %s to be a directory", d)
		}
	}
}

func TestEnsureDataDirs_ErrorWhenPathBlockedByFile(t *testing.T) {
	home := t.TempDir()
	// Create a plain file where dataDir(home) needs to create a directory — MkdirAll then
	// fails because it can't create a directory at a path already occupied by a file.
	if err := os.WriteFile(dataDir(home), []byte("blocked"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := ensureDataDirs(home); err == nil {
		t.Error("expected an error when dataDir is blocked by an existing file")
	}
}

func TestEnsureDataDirs_IdempotentWhenAlreadyExists(t *testing.T) {
	home := t.TempDir()
	if err := ensureDataDirs(home); err != nil {
		t.Fatalf("first call failed: %v", err)
	}
	// Put real content in pgdata so a second call must not wipe it.
	marker := pgVersionMarkerPath(home)
	if err := os.WriteFile(marker, []byte("16\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := ensureDataDirs(home); err != nil {
		t.Fatalf("second call failed: %v", err)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Errorf("expected marker to survive a second ensureDataDirs call: %v", err)
	}
}
