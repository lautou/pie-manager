// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPathBuilders(t *testing.T) {
	home := `C:\Users\pie`
	cases := []struct {
		name string
		fn   func(string) string
		want string
	}{
		{"dataDir", dataDir, filepath.Join(home, "PieManager")},
		{"pgDataDir", pgDataDir, filepath.Join(home, "PieManager", "pgdata")},
		{"pgBinDir", pgBinDir, filepath.Join(home, "PieManager", "pgsql", "bin")},
		{"pythonDir", pythonDir, filepath.Join(home, "PieManager", "python")},
		{"logDir", logDir, filepath.Join(home, "PieManager", "logs")},
		{"frontendDistDir", frontendDistDir, filepath.Join(home, "PieManager", "frontend_dist")},
		{"pgVersionMarkerPath", pgVersionMarkerPath, filepath.Join(home, "PieManager", "pgdata", "PG_VERSION")},
		{"postmasterPidPath", postmasterPidPath, filepath.Join(home, "PieManager", "pgdata", "postmaster.pid")},
		{"backendPidPath", backendPidPath, filepath.Join(home, "PieManager", "backend.pid")},
		{"workerPidPath", workerPidPath, filepath.Join(home, "PieManager", "worker.pid")},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := c.fn(home); got != c.want {
				t.Errorf("%s(%q) = %q, want %q", c.name, home, got, c.want)
			}
		})
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
	for _, d := range []string{dataDir(home), pgDataDir(home), pgBinDir(home), pythonDir(home), logDir(home), frontendDistDir(home)} {
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
