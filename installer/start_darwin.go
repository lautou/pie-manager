//go:build darwin

package main

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

// notify sends a macOS notification (best-effort, silent on any error).
func notify(summary, body string) {
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
	composePath := filepath.Join(target, "compose-prod.yaml")
	port := readAppPort(target)
	url := fmt.Sprintf("http://localhost:%d", port)

	if resp, err := http.Get(url); err == nil { //nolint:noctx
		resp.Body.Close()
		openBrowser(url)
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

	notify("PIE Manager", "Starting…")

	if err := ensurePodmanMachine(); err != nil {
		fmt.Printf("ERROR: %v\n", err)
		os.Exit(1)
	}

	if !podmanImageExists("quay.io/ltourreau/pie-manager-backend:" + Version) {
		notify("PIE Manager", "Downloading images…")
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

	notify("PIE Manager", "Starting services…")
	forceRecreate(composeCmd, composePath)

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
			notify("PIE Manager", msg[5:])
		}
		time.Sleep(time.Second)
	}

	notify("PIE Manager", "Ready!")
	fmt.Printf("PIE Manager available at %s\n", url)
}
