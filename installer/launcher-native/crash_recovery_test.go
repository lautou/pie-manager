// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestReadPostmasterPid_MissingFile(t *testing.T) {
	home := t.TempDir()
	_, ok := readPostmasterPid(home)
	if ok {
		t.Error("expected ok=false when postmaster.pid does not exist")
	}
}

func TestReadPostmasterPid_ValidPid(t *testing.T) {
	home := t.TempDir()
	if err := ensureDataDirs(home); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(postmasterPidPath(home), []byte("12345\n/some/pgdata\n5432\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	pid, ok := readPostmasterPid(home)
	if !ok {
		t.Fatal("expected ok=true for a well-formed postmaster.pid")
	}
	if pid != 12345 {
		t.Errorf("expected pid 12345, got %d", pid)
	}
}

func TestReadPostmasterPid_MalformedFirstLine(t *testing.T) {
	home := t.TempDir()
	if err := ensureDataDirs(home); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(postmasterPidPath(home), []byte("not-a-pid\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, ok := readPostmasterPid(home)
	if ok {
		t.Error("expected ok=false for a malformed first line")
	}
}

func TestReadPostmasterPid_EmptyFile(t *testing.T) {
	home := t.TempDir()
	if err := ensureDataDirs(home); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(postmasterPidPath(home), []byte(""), 0o644); err != nil {
		t.Fatal(err)
	}
	_, ok := readPostmasterPid(home)
	if ok {
		t.Error("expected ok=false for an empty file")
	}
}

func TestWritePidRecord_RoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "backend.pid")

	if err := writePidRecord(path, 4242, 123456789); err != nil {
		t.Fatalf("writePidRecord failed: %v", err)
	}

	pid, startTime, ok := readPidRecord(path)
	if !ok {
		t.Fatal("expected ok=true reading back a record writePidRecord just wrote")
	}
	if pid != 4242 {
		t.Errorf("pid = %d, want 4242", pid)
	}
	if startTime != 123456789 {
		t.Errorf("startTime = %d, want 123456789", startTime)
	}
}

func TestWritePidRecord_ErrorWhenDirectoryMissing(t *testing.T) {
	// os.WriteFile doesn't create missing parent directories.
	path := filepath.Join(t.TempDir(), "no-such-dir", "backend.pid")
	if err := writePidRecord(path, 1, 1); err == nil {
		t.Error("expected an error when the parent directory doesn't exist")
	}
}

func TestReadPidRecord_MissingFile(t *testing.T) {
	_, _, ok := readPidRecord(filepath.Join(t.TempDir(), "does-not-exist"))
	if ok {
		t.Error("expected ok=false when the record file does not exist")
	}
}

func TestReadPidRecord_WrongLineCount(t *testing.T) {
	for name, content := range map[string]string{
		"single line":      "4242\n",
		"three lines":      "4242\n123456789\nextra\n",
		"no newline":       "4242",
		"completely empty": "",
	} {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "record.pid")
			if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
				t.Fatal(err)
			}
			_, _, ok := readPidRecord(path)
			if ok {
				t.Errorf("expected ok=false for content %q", content)
			}
		})
	}
}

func TestReadPidRecord_MalformedPid(t *testing.T) {
	path := filepath.Join(t.TempDir(), "record.pid")
	if err := os.WriteFile(path, []byte("not-a-pid\n123456789\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, _, ok := readPidRecord(path)
	if ok {
		t.Error("expected ok=false for a malformed pid field")
	}
}

func TestReadPidRecord_MalformedStartTime(t *testing.T) {
	path := filepath.Join(t.TempDir(), "record.pid")
	if err := os.WriteFile(path, []byte("4242\nnot-a-time\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, _, ok := readPidRecord(path)
	if ok {
		t.Error("expected ok=false for a malformed start-time field")
	}
}

func TestRecoverOrphanedPostgres_NoLockFile(t *testing.T) {
	home := t.TempDir()
	if err := recoverOrphanedPostgres(home); err != nil {
		t.Errorf("expected no error when postmaster.pid does not exist, got %v", err)
	}
}

func TestRecoverOrphanedPythonProcess_NoRecord(t *testing.T) {
	if err := recoverOrphanedPythonProcess(filepath.Join(t.TempDir(), "backend.pid")); err != nil {
		t.Errorf("expected no error when the pid record does not exist, got %v", err)
	}
}

func TestRecoverFromPreviousSession_NothingToRecover(t *testing.T) {
	home := t.TempDir()
	if err := recoverFromPreviousSession(home); err != nil {
		t.Errorf("expected no error when nothing was left running, got %v", err)
	}
}
