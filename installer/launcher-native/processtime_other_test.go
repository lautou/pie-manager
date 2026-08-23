//go:build !windows

// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import "testing"

// TestProcessStartTime_ErrorsOnNonWindows runs on every non-Windows platform this module
// compiles for. The real Windows implementation (GetProcessTimes) lives in
// processtime_windows.go, tested separately in processtime_windows_test.go - matches
// hidewindow_test.go/hidewindow_windows_test.go's established split for the same reason.
func TestProcessStartTime_ErrorsOnNonWindows(t *testing.T) {
	if _, err := processStartTime(1); err == nil {
		t.Error("expected an error from the non-Windows stub")
	}
}
