#!/usr/bin/env python3
"""PIE Manager — native WebKitGTK window (no browser chrome)."""
import gi
import os
import urllib.request

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import GLib, Gtk, WebKit2

APP_TITLE = "PIE Manager"
APP_ICON = "pie-manager"
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
INSTALL_DIR = os.path.expanduser("~/.local/share/pie-manager")
DEFAULT_PORT = 14943

LOADING_HTML = """\
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  height: 100vh;
  background: #1a2744; color: #fff; font-family: sans-serif;
}
.logo { font-size: 3rem; margin-bottom: 0.5rem; }
h1 { font-size: 1.8rem; font-weight: 600; letter-spacing: 0.04em; }
.sub { color: #8899bb; margin: 0.4rem 0 2.5rem; font-size: 0.95rem; }
.track {
  width: 280px; height: 5px;
  background: #2a3a5c; border-radius: 3px; overflow: hidden;
}
.bar {
  height: 100%; width: 45%; background: #00d4aa;
  border-radius: 3px;
  animation: slide 1.6s ease-in-out infinite;
}
@keyframes slide {
  0%   { transform: translateX(-120%); }
  100% { transform: translateX(320%); }
}
.status { margin-top: 1.5rem; color: #5577aa; font-size: 0.85rem; }
</style>
</head>
<body>
  <div class="logo">🥧</div>
  <h1>PIE Manager</h1>
  <p class="sub">Portfolio Investment &amp; Savings</p>
  <div class="track"><div class="bar"></div></div>
  <p class="status">Starting services…</p>
</body></html>"""


def _read_app_port() -> int:
    env_path = os.path.join(INSTALL_DIR, ".env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("APP_PORT="):
                    return int(line.split("=", 1)[1].strip())
    except (OSError, ValueError):
        pass
    return DEFAULT_PORT


APP_URL = f"http://localhost:{_read_app_port()}"
VERSION_URL = f"{APP_URL}/api/admin/version"


class PIEWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE)
        self.set_default_size(1400, 900)
        self.set_icon_name(APP_ICON)

        settings = WebKit2.Settings()
        settings.set_enable_developer_extras(False)
        settings.set_javascript_can_open_windows_automatically(False)

        self._webview = WebKit2.WebView()
        self._webview.set_settings(settings)
        self._webview.connect("decide-policy", self._on_policy)

        ctx = self._webview.get_context()
        ctx.connect("download-started", self._on_download_started)

        self.add(self._webview)
        self.connect("destroy", Gtk.main_quit)
        self.show_all()

        # Try to connect immediately; show loading screen only if not ready
        if not self._try_navigate_direct():
            self._show_loading()

    def _try_navigate_direct(self) -> bool:
        """Return True and navigate if backend already responds."""
        try:
            req = urllib.request.urlopen(VERSION_URL, timeout=0.5)
            if req.status == 200:
                self._webview.load_uri(APP_URL)
                return True
        except Exception:
            pass
        return False

    def _show_loading(self):
        """Show animated loading screen and start polling the backend."""
        self._webview.load_html(LOADING_HTML, APP_URL)
        GLib.timeout_add(600, self._poll_backend)

    def _poll_backend(self) -> bool:
        """Poll every 600 ms; navigate to app when backend is ready."""
        try:
            req = urllib.request.urlopen(VERSION_URL, timeout=0.8)
            if req.status == 200:
                GLib.idle_add(self._webview.load_uri, APP_URL)
                return False  # stop polling
        except Exception:
            pass
        return True  # keep polling

    def _on_policy(self, _webview, decision, dtype):
        if dtype == WebKit2.PolicyDecisionType.RESPONSE:
            response = decision.get_response()
            mime = response.get_mime_type()
            if mime and "html" not in mime:
                decision.download()
                return True
        elif dtype == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            allowed = (
                uri.startswith(APP_URL) or
                uri.startswith("about:") or
                uri.startswith("data:")   # loading HTML uses data: internally
            )
            if not allowed:
                decision.ignore()
                return True
        return False

    def _on_download_started(self, _ctx, download):
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        download.connect("decide-destination", self._on_decide_destination)
        download.connect("finished", self._on_download_finished)
        download.connect("failed", self._on_download_failed)

    def _on_decide_destination(self, download, suggested_filename):
        dest = os.path.join(DOWNLOAD_DIR, suggested_filename)
        download.set_destination(f"file://{dest}")
        return True

    def _on_download_finished(self, download):
        dest = download.get_destination()
        if dest:
            self._notify(f"Backup saved to {dest.replace('file://', '')}")

    def _on_download_failed(self, download, error):
        self._notify(f"Download failed: {error.message}")

    def _notify(self, message):
        try:
            import subprocess
            subprocess.Popen(["notify-send", "-a", APP_TITLE, APP_TITLE, message])
        except Exception:
            pass


if __name__ == "__main__":
    PIEWindow()
    Gtk.main()
