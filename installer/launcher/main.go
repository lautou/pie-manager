//go:build windows

package main

import (
	"fmt"
	"io"
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

// installerDownloadURL is the stable "latest release" alias for the full
// system installer, published by build-installer.yml alongside every
// versioned release asset (see the "Create GitHub Release" step there).
const installerDownloadURL = "https://github.com/lautou/pie-manager/releases/latest/download/pie-manager-windows-amd64.exe"

var (
	user32                  = syscall.NewLazyDLL("user32.dll")
	procFindWindowW         = user32.NewProc("FindWindowW")
	procShowWindow          = user32.NewProc("ShowWindow")
	procSetForegroundWindow = user32.NewProc("SetForegroundWindow")

	shell32           = syscall.NewLazyDLL("shell32.dll")
	procShellExecuteW = shell32.NewProc("ShellExecuteW")
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
// below (Podman/container startup timeouts) instead of each inlining its own
// copy.
const errorHTMLTpl = `<!DOCTYPE html><html><body style="font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#1a1a2e;color:#e0e0e0;flex-direction:column;text-align:center;padding:0 40px"><h2>PIE Manager</h2><p style="margin-top:16px;color:#ff6b6b;line-height:1.6">%s</p></body></html>`

// showErrorScreen replaces the WebView2 page with a static error message.
func showErrorScreen(w webview2.WebView, message string) {
	w.Dispatch(func() { w.SetHtml(fmt.Sprintf(errorHTMLTpl, message)) })
}

// notInstalledHTML is shown when launcher.exe is run standalone (issue #63:
// distributed via the Microsoft Store) without the full system installer
// ever having run. It must not just point the user at an external download
// — Microsoft Store policy 10.1.2 ("Your product must be fully functional")
// rejected an earlier version of this screen that did exactly that
// ("Unusable Feature: The product fails to start with a message to download
// the App from outside the Store"). Instead, this screen's button itself
// downloads and launches the real installer (with a UAC elevation prompt —
// triggered by this explicit user action, not automatically on launch,
// which is the distinction Store certification cares about) via the bound
// triggerInstall JS function.
const notInstalledHTML = `<!DOCTYPE html>
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
    text-align: center; padding: 0 40px;
  }
  h2 { font-size: 2rem; font-weight: 300; letter-spacing: 2px; margin-bottom: 16px; }
  p { font-size: 0.95rem; color: #aaa; margin-bottom: 24px; line-height: 1.6; }
  button {
    font-family: inherit; font-size: 1rem; padding: 12px 28px;
    background: #4a9eff; color: #fff; border: none; border-radius: 6px;
    cursor: pointer;
  }
  button:disabled { background: #555; cursor: default; }
  #status { margin-top: 16px; min-height: 1.2em; }
</style>
</head>
<body>
  <h2>PIE Manager</h2>
  <p>This is the first time PIE Manager runs on this computer.<br>
  Click below to download and set up the application — Windows will ask you
  to approve the one-time setup (administrator rights required).</p>
  <button id="installBtn" onclick="startInstall()">Install PIE Manager</button>
  <p id="status"></p>
  <script>
    async function startInstall() {
      document.getElementById('installBtn').disabled = true;
      var status = document.getElementById('status');
      status.style.color = '#aaa';
      status.textContent = 'Downloading installer…';
      try {
        await triggerInstall();
        status.textContent = 'Setup launched — this window will close.';
      } catch (err) {
        status.style.color = '#ff6b6b';
        status.textContent = 'Error: ' + err;
        document.getElementById('installBtn').disabled = false;
      }
    }
  </script>
</body>
</html>`

// downloadInstaller fetches the full system installer to a temp file and
// returns its path.
func downloadInstaller() (string, error) {
	resp, err := http.Get(installerDownloadURL)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	dest := filepath.Join(os.TempDir(), "pie-manager-windows-amd64.exe")
	f, err := os.Create(dest)
	if err != nil {
		return "", err
	}
	defer f.Close()

	if _, err := io.Copy(f, resp.Body); err != nil {
		return "", err
	}
	return dest, nil
}

// runElevated launches path with a UAC elevation prompt via ShellExecuteW's
// "runas" verb — os/exec has no equivalent, since a non-elevated process
// cannot elevate a child any other way on Windows.
func runElevated(path string) error {
	verb, _ := syscall.UTF16PtrFromString("runas")
	file, _ := syscall.UTF16PtrFromString(path)
	dir, _ := syscall.UTF16PtrFromString(filepath.Dir(path))
	const swShowNormal = 1
	ret, _, _ := procShellExecuteW.Call(
		0,
		uintptr(unsafe.Pointer(verb)),
		uintptr(unsafe.Pointer(file)),
		0,
		uintptr(unsafe.Pointer(dir)),
		swShowNormal,
	)
	// ShellExecuteW returns a value > 32 on success; anything else
	// (including the user declining the UAC prompt) is a failure code.
	if ret <= 32 {
		return fmt.Errorf("ShellExecuteW failed (code %d) — did you decline the elevation prompt?", ret)
	}
	return nil
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

	// Fail fast with an actionable install button, instead of spinning on
	// Phase 1 forever — see isFullyInstalled's and notInstalledHTML's
	// comments for why this case is now reachable and why it must let the
	// user actually do something, not just point them elsewhere.
	if !isFullyInstalled() {
		err := w.Bind("triggerInstall", func() error {
			dest, err := downloadInstaller()
			if err != nil {
				return fmt.Errorf("could not download the installer: %v", err)
			}
			if err := runElevated(dest); err != nil {
				return fmt.Errorf("could not launch the installer: %v", err)
			}
			w.Terminate()
			return nil
		})
		if err != nil {
			showErrorScreen(w, "Internal error: could not initialize the installer button.")
		} else {
			w.SetHtml(notInstalledHTML)
		}
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
