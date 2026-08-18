//go:build windows

package main

import (
	"fmt"
	"html"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"syscall"
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

const windowTitle = "PIE Manager"

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
  .firewall-hint { font-size: 0.75rem; color: #666; margin-top: 32px; max-width: 420px; text-align: center; }
</style>
</head>
<body>
  <h2>PIE Manager</h2>
  <div class="version">{{VERSION}}</div>
  <p id="status">Starting services, please wait…</p>
  <div class="spinner"></div>
  <p class="firewall-hint">Windows may show a firewall alert on first launch — this is expected, the app only ever communicates locally (127.0.0.1) regardless of your answer.</p>
</body>
</html>`

// A plain <p> with no white-space handling used to be enough when this only ever showed a
// short one-line message. It now also carries a failed command's full log tail (see
// postgres.go's runCapturedCommandIn) — a real multi-line Python traceback — so this needs a
// scrollable, monospace, whitespace-preserving container instead, or that content collapses
// into one unreadable run-on line (confirmed live: this exact gap is why issue #82's
// certification failures only ever showed a bare "exit status N" with no way to see why).
const errorHTMLTpl = `<!DOCTYPE html><html><body style="font-family:Segoe UI;margin:0;background:#1a1a2e;color:#e0e0e0;padding:24px;box-sizing:border-box;height:100vh;overflow:hidden;display:flex;flex-direction:column"><h2 style="flex-shrink:0">PIE Manager</h2><pre style="color:#ff6b6b;white-space:pre-wrap;word-break:break-word;overflow-y:auto;font-family:Consolas,monospace;font-size:13px;margin-top:16px">{{MESSAGE}}</pre></body></html>`

// focusExistingWindow brings the existing PIE Manager window to the foreground.
// Returns true if a window was found. Identical to installer/launcher/main.go's own
// implementation - this is genuinely OS-glue code with no logic of its own worth sharing across
// the two separate Go modules for.
func focusExistingWindow() bool {
	title, _ := syscall.UTF16PtrFromString(windowTitle)
	hwnd, _, _ := procFindWindowW.Call(0, uintptr(unsafe.Pointer(title)))
	if hwnd != 0 {
		const swRestore = 9
		procShowWindow.Call(hwnd, swRestore)
		procSetForegroundWindow.Call(hwnd)
		return true
	}
	return false
}

// setStatus updates the status message in the WebView2 page without reloading.
func setStatus(w webview2.WebView, msg string) {
	js := fmt.Sprintf(`document.getElementById('status').textContent = %q`, msg)
	w.Dispatch(func() { w.Eval(js) })
}

func showError(w webview2.WebView, message string) {
	// Escaped, unlike the loading screen's {{VERSION}}/{{STATUS}} substitutions elsewhere in
	// this file — those only ever carry this app's own version string or fixed status text,
	// but this carries a failed command's real log output (see postgres.go's
	// runCapturedCommandIn), which can contain "<"/">"/"&" (Python type reprs like
	// "<class '...'>" are common in a traceback) that would otherwise corrupt the HTML.
	page := strings.Replace(errorHTMLTpl, "{{MESSAGE}}", html.EscapeString(message), 1)
	w.Dispatch(func() { w.SetHtml(page) })
}

func main() {
	// Single-instance: focus existing window and exit if already running.
	if focusExistingWindow() {
		os.Exit(0)
	}

	home, err := os.UserHomeDir()
	if err != nil {
		// No window has been created yet at this point - nothing meaningful to show the user.
		// This is not expected to ever actually happen on a real Windows machine.
		os.Exit(1)
	}

	exePath, err := os.Executable()
	if err != nil {
		os.Exit(1)
	}
	pkgRoot := filepath.Dir(exePath)

	// IconId: 1 matches the numeric RT_GROUP_ICON resource ID ("#1") embedded via
	// winres/winres.json - mirrors installer/launcher/main.go's own icon setup.
	w := webview2.NewWithOptions(webview2.WebViewOptions{
		Debug: false,
		WindowOptions: webview2.WindowOptions{
			IconId: 1,
		},
	})
	defer w.Destroy()

	w.SetTitle(windowTitle)
	w.SetSize(1400, 900, webview2.HintNone)
	w.SetHtml(strings.Replace(loadingHTMLTpl, "{{VERSION}}", Version, 1))

	// Written by the startup goroutine, read by the main goroutine after w.Run() returns -
	// atomic.Pointer avoids a data race between the two without needing a mutex for what is
	// otherwise a simple single-value handoff.
	var session atomic.Pointer[nativeSession]

	go func() {
		setStatus(w, "Preparing local database…")
		s, err := startupSequence(pkgRoot, home)
		if err != nil {
			showError(w, fmt.Sprintf("Failed to start PIE Manager: %v", err))
			return
		}
		session.Store(s)

		appURL := fmt.Sprintf("http://127.0.0.1:%d", s.ports.Backend)
		w.Dispatch(func() { w.Navigate(appURL) })
	}()

	w.Run()

	// w.Run() returns when the window is closed by the user - stop the backend and Postgres
	// before this process exits, so nothing is left running in the background (the accepted
	// trade-off from issue #65: no sync while the app window isn't open). session.Load() is nil
	// if the window was closed before startupSequence finished - shutdown() handles that safely.
	session.Load().shutdown()
}
