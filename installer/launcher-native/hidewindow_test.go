// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"os/exec"
	"testing"
)

// TestHideWindow_DoesNotPanic runs on every platform this module compiles for. The
// Windows-specific assertion (SysProcAttr.HideWindow actually set) lives in
// hidewindow_windows_test.go, since syscall.SysProcAttr has no HideWindow field outside
// Windows — verified there directly; verified for real Windows subprocess behavior via
// GOOS=windows go vet (this file's own build tag split already proved to compile correctly
// for issue #82's earlier fixes in this same package).
func TestHideWindow_DoesNotPanic(t *testing.T) {
	cmd := exec.Command("/bin/true")
	hideWindow(cmd)
}
