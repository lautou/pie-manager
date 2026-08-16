package main

import (
	"os"
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
