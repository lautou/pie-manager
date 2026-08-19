//go:build windows

package main

import (
	"os/exec"
	"testing"
)

// TestHideWindow_SetsHideWindowFlag is the real assertion for hideWindow's Windows behavior —
// only compiles/runs on Windows, since syscall.SysProcAttr.HideWindow doesn't exist elsewhere.
// Verified via GOOS=windows cross-compile in CI on this Linux-developed codebase, matching this
// package's established pattern for Windows-only logic (see postgres.go's runCapturedCommandIn
// history, issue #82). Asserts CreationFlags alongside HideWindow - HideWindow alone was
// confirmed live to be insufficient for Postgres's EXEC_BACKEND worker processes (see this
// file's own doc comment); CREATE_NO_WINDOW is the flag actually doing the real work.
func TestHideWindow_SetsHideWindowFlag(t *testing.T) {
	cmd := exec.Command("cmd.exe")
	hideWindow(cmd)
	if cmd.SysProcAttr == nil {
		t.Fatal("expected SysProcAttr to be set")
	}
	if !cmd.SysProcAttr.HideWindow {
		t.Error("expected HideWindow to be true")
	}
	if cmd.SysProcAttr.CreationFlags != createNoWindow {
		t.Errorf("expected CreationFlags to be CREATE_NO_WINDOW, got %v", cmd.SysProcAttr.CreationFlags)
	}
}
