//go:build linux

package main

import (
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
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
	composePath := filepath.Join(target, "compose-prod.yaml")
	port := readAppPort(target)
	url := fmt.Sprintf("http://localhost:%d", port)

	if resp, err := http.Get(url); err == nil { //nolint:noctx
		resp.Body.Close()
		if !focusExistingWindow() {
			openBrowser(url)
		}
		return
	}

	if ln, err := net.Listen("tcp", fmt.Sprintf(":%d", port)); err != nil {
		newPort := findAvailablePort(port + 1)
		fmt.Printf("Port %d is now in use, switching to %d…\n", port, newPort)
		updateEnvPort(target, newPort)
		port = newPort
		url = fmt.Sprintf("http://localhost:%d", port)
	} else {
		ln.Close()
	}

	notify("PIE Manager", "Starting…", "low")

	if !podmanImageExists("quay.io/ltourreau/pie-manager-backend:" + Version) {
		notify("PIE Manager", "Downloading images…", "low")
		for _, img := range []string{
			"quay.io/ltourreau/pie-manager-backend:" + Version,
			"quay.io/ltourreau/pie-manager-frontend:" + Version,
		} {
			fmt.Printf("  Pulling %s…\n", img)
			pull := exec.Command("podman", "pull", img)
			pull.Stdout = os.Stdout
			pull.Stderr = os.Stderr
			pull.Run() //nolint:errcheck
		}
	}

	go openBrowser(url)

	notify("PIE Manager", "Starting services…", "low")

	dir := filepath.Dir(composePath)
	parts := strings.Fields(composeCmd)
	down := exec.Command(parts[0], append(parts[1:], "-f", composePath, "down", "--remove-orphans")...)
	down.Dir = dir
	down.Stdout = io.Discard
	down.Stderr = io.Discard
	down.Run() //nolint:errcheck
	up := exec.Command(parts[0], append(parts[1:], "-f", composePath, "up", "-d")...)
	up.Dir = dir
	up.Stdout = io.Discard
	up.Stderr = os.Stderr
	up.Run() //nolint:errcheck

	fmt.Println("Waiting for PIE Manager to be ready…")
	statusMessages := map[int]string{
		5:  "  → Containers started, waiting for database…",
		15: "  → Database ready, starting backend…",
		30: "  → Backend starting (running migrations)…",
		50: "  → Still starting — first launch may take up to 90 s…",
		70: "  → Almost there…",
	}
	for i := 0; i < 90; i++ {
		resp, err := http.Get(url) //nolint:noctx
		if err == nil {
			resp.Body.Close()
			fmt.Printf("  ✓ Ready in %ds\n", i)
			break
		}
		if msg, ok := statusMessages[i]; ok {
			fmt.Println(msg)
			notify("PIE Manager", msg[5:], "low")
		}
		time.Sleep(time.Second)
	}

	notify("PIE Manager", "Ready!", "normal")
	fmt.Printf("PIE Manager available at %s\n", url)
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
