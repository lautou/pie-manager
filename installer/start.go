package main

import (
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// notify sends a desktop notification (best-effort, silent if notify-send is absent).
func notify(summary, body, urgency string) {
	if runtime.GOOS == "windows" {
		notifyWindows(summary, body)
		return
	}
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

// readAppPort reads APP_PORT from the install dir's .env file, falling back to defaultPort.
func readAppPort(target string) int {
	data, err := os.ReadFile(filepath.Join(target, ".env"))
	if err != nil {
		return defaultPort
	}
	for _, line := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(line, "APP_PORT=") {
			val := strings.TrimPrefix(line, "APP_PORT=")
			val = strings.TrimSpace(val)
			if p, err := strconv.Atoi(val); err == nil && p > 0 {
				return p
			}
		}
	}
	return defaultPort
}

func runStartWithCompose(composeCmd, target string) {
	composePath := filepath.Join(target, "compose-prod.yaml")
	port := readAppPort(target)
	url := fmt.Sprintf("http://localhost:%d", port)

	// If the app already responds, bring existing window to front.
	// On Windows the browser is managed by launcher.ps1 — don't open another one.
	if resp, err := http.Get(url); err == nil { //nolint:noctx
		resp.Body.Close()
		if runtime.GOOS != "windows" && !focusExistingWindow() {
			openBrowser(url)
		}
		return
	}

	// If the saved port is no longer free (grabbed by another app since install),
	// pick a new one and update .env so Nginx and the wrapper both use it.
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

	// Pull images if missing — no authentication needed (public registry).
	if !podmanImageExists("ghcr.io/lautou/pie-manager-backend:" + Version) {
		notify("PIE Manager", "Downloading images…", "low")
		for _, img := range []string{
			"ghcr.io/lautou/pie-manager-backend:" + Version,
			"ghcr.io/lautou/pie-manager-frontend:" + Version,
		} {
			fmt.Printf("  Pulling %s…\n", img)
			pull := exec.Command("podman", "pull", img)
			pull.Stdout = os.Stdout
			pull.Stderr = os.Stderr
			pull.Run() //nolint:errcheck
		}
	}

	// On Linux: launch the WebKitGTK window immediately (animated loading screen).
	// On Windows: the browser is opened by launcher.ps1 — skip here to avoid duplicates.
	if runtime.GOOS != "windows" {
		go openBrowser(url)
	}

	// Start containers.
	notify("PIE Manager", "Starting services…", "low")

	if runtime.GOOS == "windows" {
		// On Windows: run podman-compose inside the Podman Machine (WSL2 Fedora VM).
		wslPath := wslComposePath(composePath)
		exec.Command("podman", "machine", "ssh", "--",
			podmanComposeInMachine(), "-f", wslPath, "down", "--remove-orphans").Run() //nolint:errcheck
		up := exec.Command("podman", "machine", "ssh", "--",
			podmanComposeInMachine(), "-f", wslPath, "up", "-d")
		up.Stdout = io.Discard
		up.Stderr = os.Stderr
		up.Run() //nolint:errcheck
	} else {
	dir := filepath.Dir(composePath)
	parts := strings.Fields(composeCmd)
	// Stop cleanly first (suppressed — some containers may not exist yet)
	down := exec.Command(parts[0], append(parts[1:], "-f", composePath, "down", "--remove-orphans")...)
	down.Dir = dir
	down.Stdout = io.Discard
	down.Stderr = io.Discard
	down.Run() //nolint:errcheck
	// Start all services fresh
	up := exec.Command(parts[0], append(parts[1:], "-f", composePath, "up", "-d")...)
	up.Dir = dir
	up.Stdout = io.Discard
	up.Stderr = os.Stderr
	up.Run() //nolint:errcheck
	} // end else (Linux/macOS path)

	// Print terminal status while the window's loading screen polls the backend.
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

// updateEnvPort rewrites APP_PORT in the install dir's .env file.
func updateEnvPort(target string, port int) {
	path := filepath.Join(target, ".env")
	data, _ := os.ReadFile(path)
	re := regexp.MustCompile(`(?m)^APP_PORT=.*$`)
	updated := re.ReplaceAllString(string(data), fmt.Sprintf("APP_PORT=%d", port))
	if !strings.Contains(updated, "APP_PORT=") {
		updated += fmt.Sprintf("\nAPP_PORT=%d\n", port)
	}
	os.WriteFile(path, []byte(updated), 0644) //nolint:errcheck
}

func podmanImageExists(image string) bool {
	cmd := exec.Command("podman", "image", "exists", image)
	return cmd.Run() == nil
}

// focusExistingWindow tries to bring the PIE Manager window to the foreground.
// Returns true if an existing window was found and focused.
func focusExistingWindow() bool {
	if runtime.GOOS == "windows" {
		ps := `$w = Get-Process | Where-Object {$_.MainWindowTitle -like '*PIE Manager*'} | Select-Object -First 1
if ($w) { [void][System.Reflection.Assembly]::LoadWithPartialName('Microsoft.VisualBasic'); [Microsoft.VisualBasic.Interaction]::AppActivate($w.Id); exit 0 } else { exit 1 }`
		return exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps).Run() == nil
	}
	// Linux: try wmctrl then xdotool.
	if exec.Command("wmctrl", "-a", "PIE Manager").Run() == nil {
		return true
	}
	if out, err := exec.Command("xdotool", "search", "--name", "PIE Manager").Output(); err == nil && len(out) > 0 {
		pid := strings.TrimSpace(string(out))
		return exec.Command("xdotool", "windowactivate", pid).Run() == nil
	}
	// If wrapper.py is running a window exists even without wmctrl.
	return exec.Command("pgrep", "-f", "wrapper.py").Run() == nil
}

func openBrowser(url string) {
	if runtime.GOOS == "windows" {
		openBrowserWindows(url)
		return
	}

	home := os.Getenv("HOME")
	wrapperPath := filepath.Join(home, installDir, "wrapper.py")

	// Prefer native WebKitGTK wrapper (no browser chrome).
	if _, err := os.Stat(wrapperPath); err == nil {
		cmd := exec.Command("python3", wrapperPath)
		cmd.Stdout = io.Discard
		cmd.Stderr = io.Discard
		cmd.Start()
		return
	}

	// Fallback: Epiphany in application mode, then default browser.
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
