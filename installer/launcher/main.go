//go:build windows

package main

import (
	"fmt"
	"net/http"
	"os"
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
  <p>Starting services, please wait…</p>
  <div class="spinner"></div>
</body>
</html>`

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

// getAppPort reads APP_PORT from %APPDATA%\pie-manager\.env, falling back to 14943.
func getAppPort() int {
	appdata := os.Getenv("APPDATA")
	envPath := filepath.Join(appdata, "pie-manager", ".env")
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

func main() {
	// Single-instance: focus existing window and exit if already running.
	if focusExistingWindow() {
		os.Exit(0)
	}

	port := getAppPort()
	appURL := fmt.Sprintf("http://localhost:%d", port)
	apiURL := fmt.Sprintf("%s/api/admin/version", appURL)

	w := webview2.New(false)
	defer w.Destroy()

	w.SetTitle("PIE Manager")
	w.SetSize(1400, 900, webview2.HintNone)
	w.SetHtml(strings.Replace(loadingHTMLTpl, "{{VERSION}}", Version, 1))

	// Poll the backend in a goroutine; navigate once it responds.
	go func() {
		client := &http.Client{Timeout: 2 * time.Second}
		for i := 0; i < 90; i++ {
			resp, err := client.Get(apiURL)
			if err == nil && resp.StatusCode == 200 {
				resp.Body.Close()
				w.Dispatch(func() { w.Navigate(appURL) })
				return
			}
			time.Sleep(time.Second)
		}
		// Timeout — show error in the same window.
		w.Dispatch(func() {
			w.SetHtml(`<!DOCTYPE html><html><body style="font-family:Segoe UI;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#1a1a2e;color:#e0e0e0;flex-direction:column"><h2>PIE Manager</h2><p style="margin-top:16px;color:#ff6b6b">Backend did not respond within 90 seconds.<br>Check that the Podman machine is running.</p></body></html>`)
		})
	}()

	w.Run()
}
