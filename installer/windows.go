package main

// Windows-specific installation helpers.
// All functions in this file are only called when runtime.GOOS == "windows".

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

// windowsInstallDir returns the install directory on Windows.
// Uses %APPDATA%\pie-manager (e.g. C:\Users\user\AppData\Roaming\pie-manager)
func windowsInstallDir() string {
	appdata := os.Getenv("APPDATA")
	if appdata == "" {
		appdata = filepath.Join(os.Getenv("USERPROFILE"), "AppData", "Roaming")
	}
	return filepath.Join(appdata, "pie-manager")
}

// checkWSL2 returns true if WSL2 is available and running.
func checkWSL2() bool {
	if runtime.GOOS != "windows" {
		return true // not applicable on Linux/macOS
	}
	cmd := exec.Command("wsl", "--status")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return false
	}
	return strings.Contains(string(out), "2") || strings.Contains(string(out), "WSL")
}

// installWSL2andPodman installs WSL2 and Podman CLI in parallel, then reboots.
// Installing both before the reboot avoids a second reboot for Podman CLI.
// The popup appears first so the message survives the terminal closing.
func installWSL2andPodman() {
	fmt.Println()
	fmt.Println("WSL2 not found — installation required.")
	fmt.Println()

	// Show popup BEFORE installing so the user knows what to expect.
	preInstallPopup()

	// Install Podman CLI first (no reboot needed, can run before WSL2 reboot).
	if _, err := exec.LookPath("podman"); err != nil {
		fmt.Println("Installing Podman CLI (no reboot required for this step)...")
		installPodmanWindows() //nolint:errcheck
	}

	fmt.Println("Installing WSL2 (requesting admin permission)...")

	// Use PowerShell Start-Process -Verb RunAs to properly elevate wsl --install.
	ps := `Start-Process wsl -ArgumentList '--install' -Verb RunAs -Wait`
	err := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps).Run()
	if err != nil {
		fmt.Printf("\nWSL2 installation failed or was cancelled: %v\n", err)
		fmt.Println("To install manually, open PowerShell as Administrator and run:")
		fmt.Println("  wsl --install")
		fmt.Println("Then restart Windows and run the installer again.")
		fmt.Println()
		fmt.Print("Press Enter to exit...")
		fmt.Scanln()
		return
	}

	// Check if WSL2 is already active (reboot may not be required).
	if checkWSL2() {
		fmt.Println("WSL2 is active — no reboot needed, continuing...")
		return // caller will proceed with ensurePodmanMachineRunning
	}

	// WSL2 requires a reboot — show popup and exit.
	// The user must re-run the installer after rebooting.
	showRebootRequiredPopup()
}

// preInstallPopup shows a Windows MessageBox BEFORE installing WSL2,
// warning the user that a reboot may be required.
func preInstallPopup() {
	ps := `
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show(
    "PIE Manager needs to install WSL2 (Windows Subsystem for Linux)." + [char]10 + [char]10 +
    "If Windows needs to restart, run pie-manager-windows-amd64.exe again after rebooting." + [char]10 + [char]10 +
    "If no restart is required, installation will continue automatically.",
    'PIE Manager — WSL2 Installation',
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null`

	exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps).Run() //nolint:errcheck
}

// showRebootRequiredPopup is shown only when a reboot is actually needed.
func showRebootRequiredPopup() {
	ps := `
Add-Type -AssemblyName System.Windows.Forms
$result = [System.Windows.Forms.MessageBox]::Show(
    "Windows must restart to complete WSL2 setup." + [char]10 + [char]10 +
    "After rebooting, run pie-manager-windows-amd64.exe again to finish the installation.",
    'PIE Manager — Restart required',
    [System.Windows.Forms.MessageBoxButtons]::OKCancel,
    [System.Windows.Forms.MessageBoxIcon]::Warning
)
if ($result -eq 'OK') {
    shutdown /r /t 5
}`
	exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps).Run() //nolint:errcheck
}

// ensurePodmanMachineRunning initialises and starts the Podman WSL2 machine
// if it is not already reachable. On Windows, Podman requires a WSL2-backed VM.
func ensurePodmanMachineRunning() {
	// Quick connectivity check
	if exec.Command("podman", "info").Run() == nil {
		return // already running
	}

	fmt.Println("Initializing Podman machine (downloads ~650 MB, takes a few minutes)...")
	init := exec.Command("podman", "machine", "init")
	init.Stdout = os.Stdout
	init.Stderr = os.Stderr
	init.Run() //nolint:errcheck — may already be initialized

	fmt.Println("Starting Podman machine...")
	start := exec.Command("podman", "machine", "start")
	start.Stdout = os.Stdout
	start.Stderr = os.Stderr
	if err := start.Run(); err != nil {
		fmt.Printf("Warning: could not start Podman machine: %v\n", err)
	}

	// Install podman-compose inside the machine (Python is natively available there).
	// This avoids any Windows Python dependency.
	installPodmanComposeInMachine()
}

// checkPodmanWindows returns true if Podman is installed on Windows.
func checkPodmanWindows() bool {
	_, err := exec.LookPath("podman")
	return err == nil
}

// installPodmanWindows installs Podman CLI then podman-compose (required as
// the compose provider — podman compose on Windows needs an external binary).
func installPodmanWindows() error {
	fmt.Println("Installing Podman via winget...")
	cmd := exec.Command("winget", "install", "--id", "RedHat.Podman", "--silent", "--accept-package-agreements", "--accept-source-agreements")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return err
	}
	// podman-compose is installed inside the Podman Machine after machine init
	return nil
}

// installPodmanComposeInMachine installs podman-compose inside the Podman Machine
// (WSL2 Fedora VM). Python is available natively; pip is installed via dnf if needed.
func installPodmanComposeInMachine() {
	// Skip if already installed
	if exec.Command("podman", "machine", "ssh", "--",
		"podman-compose", "--version").Run() == nil {
		return
	}

	fmt.Println("Installing podman-compose inside Podman Machine...")

	// Ensure pip is available (install via dnf if not)
	if exec.Command("podman", "machine", "ssh", "--",
		"pip3", "--version").Run() != nil {
		fmt.Println("  Installing pip via dnf...")
		exec.Command("podman", "machine", "ssh", "--",
			"sudo", "dnf", "install", "-y", "--quiet", "python3-pip").Run() //nolint:errcheck
	}

	// Install podman-compose via pip and add ~/.local/bin to PATH in the machine
	cmd := exec.Command("podman", "machine", "ssh", "--",
		"bash", "-c",
		"pip3 install --quiet podman-compose && "+
			"grep -q '.local/bin' ~/.bashrc || "+
			"echo 'export PATH=$PATH:$HOME/.local/bin' >> ~/.bashrc")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		fmt.Printf("Warning: could not install podman-compose in machine: %v\n", err)
	}
}

// podmanComposeInMachine returns the full path to podman-compose inside the machine.
func podmanComposeInMachine() string {
	return "/home/user/.local/bin/podman-compose"
}

// wslComposePath converts a Windows absolute path to its WSL equivalent
// so compose files can be referenced from inside the Podman Machine.
func wslComposePath(winPath string) string {
	out, err := exec.Command("podman", "machine", "ssh",
		"--", "wslpath", "-u", winPath).Output()
	if err != nil {
		return winPath
	}
	return strings.TrimSpace(string(out))
}

// createWindowsShortcut creates a .lnk shortcut in the Start Menu.
// target is the launcher.ps1 script path; the shortcut runs it via PowerShell.
func createWindowsShortcut(target, name, icoPath string) error {
	startMenu := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs")
	shortcutPath := filepath.Join(startMenu, name+".lnk")

	// The shortcut targets PowerShell running launcher.ps1 which:
	// - Starts containers (pie-manager.exe start) in background
	// - Waits for the app to be ready
	// - Opens Edge in --app mode (no address bar) or default browser
	ps := fmt.Sprintf(`
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('%s')
$Shortcut.TargetPath = 'powershell.exe'
$Shortcut.Arguments = '-ExecutionPolicy Bypass -WindowStyle Hidden -File "%s"'
$Shortcut.Description = 'PIE Manager — Portfolio Tracker'
$Shortcut.IconLocation = '%s,0'
$Shortcut.Save()
`, shortcutPath, target, icoPath)

	cmd := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

// openBrowserWindows opens the app in the default browser.
// rundll32 url.dll,FileProtocolHandler is the most reliable way to open
// a URL from any Windows process context (including non-interactive ones).
func openBrowserWindows(url string) {
	// Primary: rundll32 (works from any context)
	if exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start() == nil {
		return
	}
	// Fallback: PowerShell Start-Process
	exec.Command("powershell", "-NoProfile", "-WindowStyle", "Hidden",
		"-Command", "Start-Process '" + url + "'").Start() //nolint:errcheck
}

// notifyWindows sends a Windows balloon notification via PowerShell.
func notifyWindows(title, message string) {
	ps := fmt.Sprintf(`
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true
$notify.ShowBalloonTip(5000, '%s', '%s', [System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Seconds 6
$notify.Dispose()
`, title, message)
	exec.Command("powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps).Start()
}
