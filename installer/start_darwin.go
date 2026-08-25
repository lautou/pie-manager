//go:build darwin

// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

// notify sends a macOS notification (best-effort, silent on any error). `urgency` exists
// only to match Linux's notify signature — unified so performStart's shared core (common.go)
// can call notify uniformly across platforms; macOS notifications have no urgency concept,
// so it's accepted and ignored here.
func notify(summary, body, urgency string) {
	script := fmt.Sprintf(`display notification %q with title %q`, body, summary)
	exec.Command("osascript", "-e", script).Run() //nolint:errcheck
}

// openBrowser opens url in the default browser.
func openBrowser(url string) {
	exec.Command("open", url).Run() //nolint:errcheck
}

func runStart() {
	home := os.Getenv("HOME")
	target := filepath.Join(home, installDir)
	composeCmd := detectComposeCmd()
	runStartWithCompose(composeCmd, target)
}

func runStartWithCompose(composeCmd, target string) {
	performStart(composeCmd, target, ensurePodmanMachine, openBrowser)
}
