//go:build linux

// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// notify sends a desktop notification (best-effort, silent if notify-send is absent).
func notify(summary, body, urgency string) {
	args := []string{"-a", "PIE Manager", "-u", urgency}
	if body != "" {
		args = append(args, summary, body)
	} else {
		args = append(args, summary)
	}
	exec.Command("notify-send", args...).Run() //nolint:errcheck
}

func runStart() {
	home := os.Getenv("HOME")
	target := filepath.Join(home, installDir)
	composeCmd := detectComposeCmd()
	runStartWithCompose(composeCmd, target)
}

func runStartWithCompose(composeCmd, target string) {
	performStart(composeCmd, target,
		func() error { return nil },
		func(url string) {
			if !focusExistingWindow() {
				openBrowser(url)
			}
		},
	)
}

// focusExistingWindow tries to bring the PIE Manager window to the foreground.
func focusExistingWindow() bool {
	if exec.Command("wmctrl", "-a", "PIE Manager").Run() == nil {
		return true
	}
	if out, err := exec.Command("xdotool", "search", "--name", "PIE Manager").Output(); err == nil && len(out) > 0 {
		pid := strings.TrimSpace(string(out))
		return exec.Command("xdotool", "windowactivate", pid).Run() == nil
	}
	return exec.Command("pgrep", "-f", "wrapper.py").Run() == nil
}

func openBrowser(url string) {
	home := os.Getenv("HOME")
	wrapperPath := filepath.Join(home, installDir, "wrapper.py")

	if _, err := os.Stat(wrapperPath); err == nil {
		cmd := exec.Command("python3", wrapperPath)
		cmd.Stdout = io.Discard
		cmd.Stderr = io.Discard
		cmd.Start()
		return
	}

	browsers := [][]string{
		{"epiphany", "--application-mode", url},
		{"xdg-open", url},
		{"open", url},
	}
	for _, b := range browsers {
		if _, err := exec.LookPath(b[0]); err == nil {
			cmd := exec.Command(b[0], b[1:]...)
			cmd.Stdout = io.Discard
			cmd.Stderr = io.Discard
			cmd.Start()
			return
		}
	}
}
