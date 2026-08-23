//go:build windows

// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"os/exec"
	"testing"
)

// TestProcessStartTime_ReturnsNonZeroForARealProcess is the real assertion for
// processStartTime's Windows behavior — only compiles/runs on Windows, since the underlying
// GetProcessTimes syscall doesn't exist elsewhere. Verified via GOOS=windows cross-compile in
// CI, matching this package's established pattern for Windows-only logic (see
// hidewindow_windows_test.go).
func TestProcessStartTime_ReturnsNonZeroForARealProcess(t *testing.T) {
	cmd := exec.Command("cmd.exe", "/c", "exit")
	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start a real process to query: %v", err)
	}
	defer func() { _, _ = cmd.Process.Wait() }()

	start, err := processStartTime(cmd.Process.Pid)
	if err != nil {
		t.Fatalf("processStartTime failed for a real, just-started process: %v", err)
	}
	if start == 0 {
		t.Error("expected a non-zero start time for a real process")
	}
}

func TestProcessStartTime_ErrorsForInvalidPid(t *testing.T) {
	// A pid this large is virtually guaranteed not to correspond to any real process.
	if _, err := processStartTime(999999999); err == nil {
		t.Error("expected an error for a pid that doesn't correspond to any real process")
	}
}
