//go:build !windows

// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import "os/exec"

// hideWindow is a no-op on non-Windows platforms — syscall.SysProcAttr has no HideWindow field
// outside Windows, and there is no console-window-per-subprocess behavior to suppress. Exists so
// postgres.go/backend.go can call it unconditionally without a build-tag branch of their own.
// The blank assignment gives this function a real statement to instrument — an empty body
// reports as "[no statements]"/0.0% in `go tool cover` regardless of test coverage, a Go
// tooling quirk confirmed independently of this codebase, not a sign of an untested path.
func hideWindow(cmd *exec.Cmd) {
	_ = cmd
}
