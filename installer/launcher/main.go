//go:build windows

package main

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"

	"github.com/jchv/go-webview2"
)

// Version is injected at build time via -ldflags "-X main.Version=x.y.z"
var Version = "dev"

var (
	user32                  = syscall.NewLazyDLL("user32.dll")
	procFindWindowW         = user32.NewProc("FindWindowW")
	procShowWindow          = user32.NewProc("ShowWindow")
	procSetForegroundWindow = user32.NewProc("SetForegroundWindow")
)

const loadingHTMLTpl = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    height: 100vh; background: #1a1a2e; color: #e0e0e0;
  }
  h2 { font-size: 2rem; font-weight: 300; letter-spacing: 2px; margin-bottom: 8px; }
  .version { font-size: 0.8rem; color: #888; margin-bottom: 40px; }
  p  { font-size: 0.95rem; color: #aaa; margin-bottom: 24px; }
  .spinner {
    width: 40px; height: 40px;
    border: 3px solid #333;
    border-top: 3px solid #4a9eff;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
  <h2>PIE Manager</h2>
  <div class="version">{{VERSION}}</div>
  <p id="status">Starting services, please wait…</p>
  <div class="spinner"></div>
</body>
</html>`

// errorHTMLTpl renders a static error screen — no spinner, since whatever
// this reports has already been given up on. Shared by every failure case
// below (not installed, Podman/container startup timeouts) instead of each
// inlining its own copy.
const errorHTMLTpl = `<!DOCTYPE html><html><body style="font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#1a1a2e;color:#e0e0e0;flex-direction:column;text-align:center;padding:0 40px"><h2>PIE Manager</h2><p style="margin-top:16px;color:#ff6b6b;line-height:1.6">%s</p></body></html>`

// showErrorScreen replaces the WebView2 page with a static error message.
func showErrorScreen(w webview2.WebView, message string) {
	w.Dispatch(func() { w.SetHtml(fmt.Sprintf(errorHTMLTpl, message)) })
}

// focusExistingWindow brings the existing PIE Manager window to the foreground.
// Returns true if a window was found.
func focusExistingWindow() bool {
	title, _ := syscall.UTF16PtrFromString("PIE Manager")
	hwnd, _, _ := procFindWindowW.Call(0, uintptr(unsafe.Pointer(title)))
	if hwnd != 0 {
		const swRestore = 9
		procShowWindow.Call(hwnd, swRestore)
		procSetForegroundWindow.Call(hwnd)
		return true
	}
	return false
}

// pieManagerEnvPath returns the path to the .env file written by the real
// system installer (pie-manager-windows-amd64.exe) once it has finished
// setting up WSL2/Podman/the app containers.
func pieManagerEnvPath() string {
	return filepath.Join(os.Getenv("APPDATA"), "pie-manager", ".env")
}

// isFullyInstalled reports whether the real system installer has ever run on
// this machine. launcher.exe can now be launched standalone — distributed
// via the Microsoft Store (issue #63), it no longer requires the local
// embed-write-shortcut-launch path that always ran it right after the
// installer set up Podman. Without this check, a user who finds "PIE
// Manager" in the Store and installs it directly (skipping the real
// installer) hits Phase 1/2 below with Podman never installed at all —
// confirmed live as a real Microsoft Store certification failure ("The
// product loads indefinitely at launch") on a clean test machine.
func isFullyInstalled() bool {
	_, err := os.Stat(pieManagerEnvPath())
	return err == nil
}

// getAppPort reads APP_PORT from %APPDATA%\pie-manager\.env, falling back to 14943.
func getAppPort() int {
	envPath := pieManagerEnvPath()
	port := 14943

	if data, err := os.ReadFile(envPath); err == nil {
		for _, line := range strings.Split(string(data), "\n") {
			if strings.HasPrefix(line, "APP_PORT=") {
				val := strings.TrimSpace(strings.TrimPrefix(line, "APP_PORT="))
				if p, err := strconv.Atoi(val); err == nil && p > 0 {
					port = p
				}
			}
		}
	}
	return port
}

// setStatus updates the status message in the WebView2 page without reloading.
func setStatus(w webview2.WebView, msg string) {
	js := fmt.Sprintf(`document.getElementById('status').textContent = %q`, msg)
	w.Dispatch(func() { w.Eval(js) })
}

const noWindow = 0x08000000 // CREATE_NO_WINDOW — suppresses console window for child processes

// machineIsRunning checks if the Podman Machine is running.
func machineIsRunning() bool {
	cmd := exec.Command("podman", "machine", "list", "--format", "{{.LastUp}}")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	out, err := cmd.Output()
	return err == nil && strings.Contains(strings.ToLower(string(out)), "running")
}

func main() {
	// Single-instance: focus existing window and exit if already running.
	if focusExistingWindow() {
		os.Exit(0)
	}

	port := getAppPort()
	appURL := fmt.Sprintf("http://localhost:%d", port)
	apiURL := fmt.Sprintf("%s/api/admin/version", appURL)

	// IconId: 1 matches the numeric RT_GROUP_ICON resource ID ("#1") embedded
	// via winres/winres.json — go-webview2's window class otherwise falls
	// back to the generic Win32 stock icon (IDI_APPLICATION) when IconId is
	// left at its zero value, which is what rendered as a blank/generic
	// title bar icon before this fix.
	w := webview2.NewWithOptions(webview2.WebViewOptions{
		Debug: false,
		WindowOptions: webview2.WindowOptions{
			IconId: 1,
		},
	})
	defer w.Destroy()

	w.SetTitle("PIE Manager")
	w.SetSize(1400, 900, webview2.HintNone)
	w.SetHtml(strings.Replace(loadingHTMLTpl, "{{VERSION}}", Version, 1))

	// Fail fast, with a clear message, instead of spinning on Phase 1 forever
	// — see isFullyInstalled's comment for why this case is now reachable.
	if !isFullyInstalled() {
		showErrorScreen(w, "PIE Manager is not installed yet.<br>"+
			"Please download and run the full installer first:<br>"+
			"github.com/lautou/pie-manager/releases/latest")
		w.Run()
		return
	}

	go func() {
		// ── Phase 1: Wait for Podman Machine — bounded. A real end-user
		// install can legitimately take up to a minute or so for a cold
		// Podman Machine start, but it must never spin forever: confirmed
		// live as a real Microsoft Store certification failure ("The
		// product loads indefinitely at launch") on a machine where Podman
		// was never installed at all (isFullyInstalled guards the common
		// case above; this timeout is defense-in-depth for a broken/
		// partial install where .env exists but Podman itself doesn't).
		if !machineIsRunning() {
			setStatus(w, "Podman machine starting…")
			deadline := time.Now().Add(90 * time.Second)
			for !machineIsRunning() {
				if time.Now().After(deadline) {
					showErrorScreen(w, "Podman machine did not start within 90 seconds.<br>"+
						"Please try restarting PIE Manager, or reinstall if the problem persists.")
					return
				}
				time.Sleep(2 * time.Second)
			}
		}

		// ── Phase 2: Wait for port to open (HAProxy + containers) — bounded,
		// same reasoning as Phase 1.
		setStatus(w, "Containers starting…")
		addr := fmt.Sprintf("localhost:%d", port)
		containersDeadline := time.Now().Add(60 * time.Second)
		for {
			conn, err := net.DialTimeout("tcp", addr, time.Second)
			if err == nil {
				conn.Close()
				break
			}
			if time.Now().After(containersDeadline) {
				showErrorScreen(w, "Containers did not start within 60 seconds.<br>"+
					"Please try restarting PIE Manager, or reinstall if the problem persists.")
				return
			}
			time.Sleep(time.Second)
		}

		// ── Phase 3: Poll /api/admin/version — 30 s max ──────────────────────────
		setStatus(w, "Connecting to application…")
		client := &http.Client{Timeout: 2 * time.Second}
		apiDeadline := time.Now().Add(30 * time.Second)
		for time.Now().Before(apiDeadline) {
			resp, err := client.Get(apiURL)
			if err == nil && resp.StatusCode == 200 {
				resp.Body.Close()
				w.Dispatch(func() { w.Navigate(appURL) })
				return
			}
			time.Sleep(time.Second)
		}

		// Phase 3 timed out — backend reachable but not responding correctly.
		showErrorScreen(w, "Application did not respond within 30 seconds.<br>"+
			"HAProxy is reachable but the backend may still be starting.<br>"+
			"Please try again in a few seconds.")
	}()

	w.Run()
}
