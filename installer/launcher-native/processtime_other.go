//go:build !windows

// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import "fmt"

// processStartTime has no real implementation outside Windows - this whole launcher only ever
// runs there (see hidewindow_other.go for the same pattern applied to console-window
// suppression). Exists so crash_recovery.go can call it unconditionally without a build-tag
// branch of its own, and so `go vet`/`go test` succeed on this (Linux) CI runner.
func processStartTime(pid int) (uint64, error) {
	return 0, fmt.Errorf("processStartTime is only implemented on windows (pid %d)", pid)
}
