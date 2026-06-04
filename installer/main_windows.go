//go:build windows

package main

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

//go:embed assets/compose-prod.yaml
var composeProd []byte

//go:embed assets/haproxy.cfg
var haproxyCfg []byte

//go:embed assets/pie-manager.ico
var iconICO []byte

const noWindow = 0x08000000 // CREATE_NO_WINDOW

var logFilePath string

func logMessage(message string) {
	_, statErr := os.Stat(logFilePath)
	f, err := os.OpenFile(logFilePath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	defer f.Close()
	if os.IsNotExist(statErr) {
		f.Write([]byte{0xEF, 0xBB, 0xBF}) // UTF-8 BOM for Windows compatibility
	}
	ts := time.Now().Format("2006-01-02 15:04:05")
	fmt.Fprintf(f, "[%s] %s\n", ts, message)
}

// run executes a command silently (no console window, no output).
func run(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("%v (output: %s)", err, strings.TrimSpace(string(out)))
	}
	return nil
}

// runPS executes a PowerShell command silently and returns its trimmed output.
func runPS(script string) (string, error) {
	cmd := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	out, err := cmd.Output()
	return strings.TrimSpace(string(out)), err
}

func isAdmin() bool {
	_, err := os.Open("\\\\.\\PHYSICALDRIVE0")
	return err == nil
}

func isWSL2Ready() bool {
	out, err := runPS(`(Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux).State`)
	if err != nil || !strings.EqualFold(out, "Enabled") {
		return false
	}
	out, err = runPS(`(Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform).State`)
	return err == nil && strings.EqualFold(out, "Enabled")
}

// refreshPath reloads PATH from the Windows registry into the current
// process environment. Required after winget installs a binary — the
// installer updates the registry PATH but the running process still holds
// the old snapshot from when it started.
func refreshPath() {
	sys, _ := runPS(`[System.Environment]::GetEnvironmentVariable("Path","Machine")`)
	usr, _ := runPS(`[System.Environment]::GetEnvironmentVariable("Path","User")`)
	merged := strings.TrimRight(usr, ";") + ";" + strings.TrimRight(sys, ";")
	if merged != ";" {
		os.Setenv("PATH", merged)
	}
}

type podmanMachine struct {
	Name    string `json:"Name"`
	Running bool   `json:"Running"`
}

func listPodmanMachines() ([]podmanMachine, error) {
	cmd := exec.Command("podman", "machine", "list", "--format", "json")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	out, err := cmd.Output()
	if err != nil {
		return nil, err
	}
	var machines []podmanMachine
	if err := json.Unmarshal(out, &machines); err != nil {
		return nil, err
	}
	return machines, nil
}

// isPodmanMachineInitialized returns true if at least one machine exists
// (JSON array non-empty). Podman returns [] cleanly when no machine exists.
func isPodmanMachineInitialized() bool {
	machines, err := listPodmanMachines()
	return err == nil && len(machines) > 0
}

// isPodmanMachineRunning checks the Running boolean field from the JSON output —
// language-independent, no string parsing.
func isPodmanMachineRunning() bool {
	machines, err := listPodmanMachines()
	return err == nil && len(machines) > 0 && machines[0].Running
}

func isPodmanInstalled() bool {
	cmd := exec.Command("winget", "list", "--id", "RedHat.Podman")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	return cmd.Run() == nil
}

func isDockerComposeInstalled() bool {
	cmd := exec.Command("winget", "list", "--id", "Docker.DockerCompose")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	return cmd.Run() == nil
}

func rebootPending() bool {
	out, err := runPS(`(Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending").ToString()`)
	return err == nil && strings.EqualFold(out, "True")
}

func windowsInstallDir() string {
	appdata := os.Getenv("APPDATA")
	if appdata == "" {
		appdata = filepath.Join(os.Getenv("USERPROFILE"), "AppData", "Roaming")
	}
	return filepath.Join(appdata, "pie-manager")
}

func configureWSL() error {
	userProfile := os.Getenv("USERPROFILE")
	if userProfile == "" {
		return fmt.Errorf("USERPROFILE not set")
	}
	cores := runtime.NumCPU() / 2
	if cores < 2 {
		cores = 2
	}
	content := fmt.Sprintf("[wsl2]\nmemory=4GB\nprocessors=%d\n", cores)
	return os.WriteFile(filepath.Join(userProfile, ".wslconfig"), []byte(content), 0644)
}

func popup(title, msg string) {
	ps := fmt.Sprintf(`Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show("%s","%s","OK","Information")`, msg, title)
	cmd := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	cmd.Run() //nolint:errcheck
}

func main() {
	exePath, _ := os.Executable()
	logFilePath = filepath.Join(filepath.Dir(exePath), "install-prereq.log")

	logMessage("=== PIE Manager — Prerequisite Installer ===")

	if !isAdmin() {
		logMessage("FATAL: not running as Administrator")
		popup("Erreur", fmt.Sprintf("Ce programme doit être lancé en tant qu'Administrateur.\nConsultez le fichier journal :\n%s", logFilePath))
		os.Exit(1)
	}
	logMessage("OK: Administrator rights confirmed")

	if err := configureWSL(); err != nil {
		logMessage(fmt.Sprintf("WARN: .wslconfig not written: %v", err))
	} else {
		logMessage("OK: .wslconfig written (4GB RAM, NumCPU/2 processors)")
	}

	systemChanged := false

	// ── WSL2 ─────────────────────────────────────────────────────────────────
	fmt.Println("=== PIE Manager — Installation de WSL2 ===")
	if isWSL2Ready() {
		fmt.Println("WSL2 déjà installé.")
		logMessage("SKIP: WSL2 already installed")
	} else {
		logMessage("INFO: running wsl --install --no-distribution...")
		wsl := exec.Command("wsl", "--install", "--no-distribution")
		wsl.Stdout = os.Stdout
		wsl.Stderr = os.Stderr
		if err := wsl.Run(); err != nil {
			logMessage(fmt.Sprintf("FATAL: WSL2 install failed: %v", err))
			popup("Erreur", fmt.Sprintf("L'installation de WSL2 a échoué.\nConsultez le fichier journal :\n%s", logFilePath))
			os.Exit(1)
		}
		logMessage("OK: WSL2 install succeeded")
		systemChanged = true
	}

	// ── Podman CLI ───────────────────────────────────────────────────────────
	fmt.Println("=== PIE Manager — Installation de Podman CLI ===")
	if isPodmanInstalled() {
		fmt.Println("Podman CLI déjà installé.")
		logMessage("SKIP: Podman CLI already installed")
	} else {
		logMessage("INFO: running winget install RedHat.Podman...")
		podman := exec.Command("winget", "install", "RedHat.Podman",
			"-h", "--accept-package-agreements", "--accept-source-agreements")
		podman.Stdout = os.Stdout
		podman.Stderr = os.Stderr
		if err := podman.Run(); err != nil {
			logMessage(fmt.Sprintf("FATAL: Podman install failed: %v", err))
			popup("Erreur", fmt.Sprintf("L'installation de Podman CLI a échoué.\nConsultez le fichier journal :\n%s", logFilePath))
			os.Exit(1)
		}
		logMessage("OK: Podman CLI install succeeded")
		refreshPath()
		logMessage("INFO: PATH refreshed from registry")
		systemChanged = true
	}

	// ── Docker Compose ───────────────────────────────────────────────────────
	fmt.Println("=== PIE Manager — Installation de Docker Compose ===")
	if isDockerComposeInstalled() {
		fmt.Println("Docker Compose déjà installé.")
		logMessage("SKIP: Docker Compose already installed")
	} else {
		logMessage("INFO: running winget install Docker.DockerCompose...")
		compose := exec.Command("winget", "install", "Docker.DockerCompose",
			"-h", "--accept-package-agreements", "--accept-source-agreements")
		compose.Stdout = os.Stdout
		compose.Stderr = os.Stderr
		if err := compose.Run(); err != nil {
			logMessage(fmt.Sprintf("FATAL: Docker Compose install failed: %v", err))
			popup("Erreur", fmt.Sprintf("L'installation de Docker Compose a échoué.\nConsultez le fichier journal :\n%s", logFilePath))
			os.Exit(1)
		}
		logMessage("OK: Docker Compose install succeeded")
		refreshPath()
		logMessage("INFO: PATH refreshed from registry")
	}

	// ── Reboot check — only if we actually changed something this run ─────────
	// Guards against a reboot loop: after a reboot, the CBS\RebootPending key
	// may still be present for ~30s while TrustedInstaller finishes cleanup.
	// If systemChanged is false, we skipped both installs → no reboot needed.
	if systemChanged && rebootPending() {
		logMessage("INFO: reboot required (CBS registry key present)")

		// Register RunOnce so Windows auto-resumes this installer after the
		// user logs back in. RunOnce runs in the user session (correct HKCU
		// and %USERPROFILE%), then Windows deletes the entry automatically.
		runOnceCmd := fmt.Sprintf(`Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "PIEManagerResume" -Value '"%s"'`, exePath)
		if _, err := runPS(runOnceCmd); err != nil {
			logMessage(fmt.Sprintf("WARN: could not register RunOnce: %v", err))
		} else {
			logMessage("OK: RunOnce entry registered for auto-resume after reboot")
		}

		popup("Redémarrage requis",
			"WSL2 et Podman CLI ont été installés.\n\nUn redémarrage est nécessaire. L'installeur reprendra automatiquement après le redémarrage pour finaliser la configuration.\n\nCliquez OK pour redémarrer.")
		run("shutdown", "/r", "/t", "5") //nolint:errcheck
		logMessage("=== END (reboot pending) ===")
		os.Exit(0)
	}
	logMessage("INFO: no reboot required (nothing changed or reboot already done)")

	// ── Podman Machine ───────────────────────────────────────────────────────
	// Only reachable once WSL2 is fully operational (no reboot pending).
	fmt.Println("=== PIE Manager — Initialisation de la machine Podman ===")
	if isPodmanMachineInitialized() {
		fmt.Println("Machine Podman déjà initialisée.")
		logMessage("SKIP: Podman machine already initialized")
	} else {
		logMessage("INFO: running podman machine init...")
		pm := exec.Command("podman", "machine", "init")
		pm.Stdout = os.Stdout
		pm.Stderr = os.Stderr
		if err := pm.Run(); err != nil {
			logMessage(fmt.Sprintf("FATAL: podman machine init failed: %v", err))
			popup("Erreur", fmt.Sprintf("L'initialisation de la machine Podman a échoué.\nConsultez le fichier journal :\n%s", logFilePath))
			os.Exit(1)
		}
		logMessage("OK: Podman machine initialized")
	}

	// ── Podman Machine (start) ────────────────────────────────────────────────
	fmt.Println("=== PIE Manager — Démarrage de la machine Podman ===")
	if isPodmanMachineRunning() {
		fmt.Println("Machine Podman déjà démarrée.")
		logMessage("SKIP: Podman machine already running")
	} else {
		logMessage("INFO: running podman machine start...")
		start := exec.Command("podman", "machine", "start")
		start.Stdout = os.Stdout
		start.Stderr = os.Stderr
		if err := start.Run(); err != nil {
			logMessage(fmt.Sprintf("FATAL: podman machine start failed: %v", err))
			popup("Erreur", fmt.Sprintf("Le démarrage de la machine Podman a échoué.\nConsultez le fichier journal :\n%s", logFilePath))
			os.Exit(1)
		}
		logMessage("OK: Podman machine started")
	}

	// ── Enable podman-restart.service for auto-restart of containers ──────────
	// The ~/.config/systemd/user directory may not exist or may lack correct
	// ownership, which causes "Access denied" on systemctl --user enable.
	// Fix: create the directory, ensure ownership, then enable the service.
	// loginctl enable-linger allows user services to run without a login session.
	fmt.Println("=== PIE Manager — Activation du redémarrage automatique des containers ===")
	logMessage("INFO: configuring podman-restart.service inside Podman Machine...")
	setupCmd := `sudo loginctl enable-linger $USER && ` +
		`mkdir -p ~/.config/systemd/user && ` +
		`sudo chown -R $USER:$USER ~/.config && ` +
		`systemctl --user enable podman-restart.service`
	if err := run("podman", "machine", "ssh", "--", "bash", "-c", setupCmd); err != nil {
		logMessage(fmt.Sprintf("WARN: could not configure podman-restart.service: %v", err))
	} else {
		logMessage("OK: podman-restart.service enabled — containers will auto-restart at machine start")
	}

	// ── Deploy compose files and start containers ─────────────────────────────
	fmt.Println("=== PIE Manager — Déploiement et démarrage des containers ===")
	target := windowsInstallDir()
	if err := os.MkdirAll(target, 0755); err != nil {
		logMessage(fmt.Sprintf("FATAL: could not create install dir: %v", err))
		popup("Erreur", fmt.Sprintf("Impossible de créer le répertoire d'installation.\nConsultez le fichier journal :\n%s", logFilePath))
		os.Exit(1)
	}
	os.WriteFile(filepath.Join(target, "compose-prod.yaml"), composeProd, 0644) //nolint:errcheck
	os.WriteFile(filepath.Join(target, "haproxy.cfg"), haproxyCfg, 0644)         //nolint:errcheck

	// Always overwrite .env with the current version.
	// Preserve the existing port if one is configured; otherwise find a free one.
	envPath := filepath.Join(target, ".env")
	port := defaultPort
	// Stop existing containers first so the port is freed before we check
	// availability. Without this, our own HAProxy would appear to "block" the
	// port and force an unnecessary port change on every reinstall.
	composePath := filepath.Join(target, "compose-prod.yaml")
	logMessage("INFO: stopping existing containers before port check...")
	down := exec.Command("podman", "compose", "-f", composePath, "down", "--remove-orphans")
	down.Env = append(os.Environ(), "PODMAN_COMPOSE_WARNING_LOGS=false")
	down.Stdout = os.Stdout
	down.Stderr = os.Stderr
	down.Run() //nolint:errcheck — best-effort, containers may not exist yet

	// Read saved port; verify it is still free; fall back to next free port.
	if data, err := os.ReadFile(envPath); err == nil {
		for _, line := range strings.Split(string(data), "\n") {
			if strings.HasPrefix(line, "APP_PORT=") {
				if p, err := strconv.Atoi(strings.TrimSpace(strings.TrimPrefix(line, "APP_PORT="))); err == nil && p > 0 {
					port = p
				}
			}
		}
	}
	if ln, err := net.Listen("tcp", fmt.Sprintf(":%d", port)); err != nil {
		newPort := findAvailablePort(port + 1)
		logMessage(fmt.Sprintf("INFO: port %d in use by another app, switching to %d", port, newPort))
		port = newPort
	} else {
		ln.Close()
	}

	envContent := fmt.Sprintf("APP_VERSION=%s\nINSTALLER_VERSION=%s\nAPP_PORT=%d\n", Version, Version, port)
	os.WriteFile(envPath, []byte(envContent), 0644) //nolint:errcheck
	logMessage(fmt.Sprintf("INFO: .env written (version=%s port=%d)", Version, port))

	logMessage("INFO: running podman compose up -d...")
	up := exec.Command("podman", "compose", "-f", composePath, "up", "-d", "--remove-orphans")
	up.Env = append(os.Environ(), "PODMAN_COMPOSE_WARNING_LOGS=false")
	up.Stdout = os.Stdout
	up.Stderr = os.Stderr
	if err := up.Run(); err != nil {
		logMessage(fmt.Sprintf("FATAL: podman compose up failed: %v", err))
		popup("Erreur", fmt.Sprintf("Le démarrage des containers a échoué.\nConsultez le fichier journal :\n%s", logFilePath))
		os.Exit(1)
	}
	logMessage("OK: containers started")

	// Prune unused images — removes previous versions of pie-manager images,
	// the old nginx image, and any other untagged layers no longer referenced.
	logMessage("INFO: pruning unused images...")
	prune := exec.Command("podman", "image", "prune", "-af")
	prune.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	if err := prune.Run(); err != nil {
		logMessage(fmt.Sprintf("WARN: image prune failed: %v", err))
	} else {
		logMessage("OK: unused images removed")
	}

	// ── Auto-start at login (Task Scheduler + wscript invisible launcher) ────────
	// wscript.exe is a GUI-subsystem binary — it never creates a console window,
	// unlike powershell.exe which flashes a window even with -WindowStyle Hidden.
	// The .vbs script passes SW_HIDE (0) to WshShell.Run so podman starts fully
	// invisible. -Force makes the task registration idempotent.
	logMessage("INFO: registering auto-start task via Task Scheduler (wscript method)...")

	vbsPath := filepath.Join(target, "start-podman.vbs")
	vbsContent := `CreateObject("WScript.Shell").Run "podman machine start", 0, False`
	if err := os.WriteFile(vbsPath, []byte(vbsContent), 0644); err != nil {
		logMessage(fmt.Sprintf("WARN: could not write VBS launcher: %v", err))
	} else {
		logMessage("OK: VBS invisible launcher written to " + vbsPath)
	}

	autoStart := fmt.Sprintf(
		`$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument '/B /NoLogo "%s"'
Register-ScheduledTask `+
			`-TaskName "PIEManager - Start Podman Machine" `+
			`-Action $action `+
			`-Trigger (New-ScheduledTaskTrigger -AtLogOn) `+
			`-Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)) `+
			`-Force | Out-Null`,
		vbsPath)
	if _, err := runPS(autoStart); err != nil {
		logMessage(fmt.Sprintf("WARN: could not register auto-start task: %v", err))
	} else {
		logMessage("OK: auto-start task registered (100%% invisible via wscript, at login)")
	}

	// ── Desktop integration ───────────────────────────────────────────────────
	// launcher.ps1 : reads port from .env, focuses existing Edge window if
	// already open, otherwise polls until the app responds, then opens Edge
	// in --app mode (no address bar). Does NOT start containers.
	// open-app.vbs  : runs launcher.ps1 via wscript.exe (0 = SW_HIDE) so no
	// console window flashes when the user clicks the Start Menu icon.
	fmt.Println("=== PIE Manager — Intégration bureau ===")
	logMessage("INFO: deploying launcher and desktop shortcut...")

	launcherPath := filepath.Join(target, "launcher.ps1")
	launcherContent := `# PIE Manager — open the app in the browser.
# Containers start automatically at login; this script just opens the browser.

# Read port from .env
$envFile = Join-Path $PSScriptRoot ".env"
$port = 14943
if (Test-Path $envFile) {
    $m = Select-String -Path $envFile -Pattern "^APP_PORT=(\d+)" | Select-Object -First 1
    if ($m) { $port = [int]$m.Matches.Groups[1].Value }
}
$url = "http://localhost:$port"

# Bring existing Edge window to front if already open — skip loading screen
$eg = Get-Process msedge -ErrorAction SilentlyContinue |
      Where-Object { $_.MainWindowTitle -like "*PIE Manager*" -or $_.MainWindowTitle -like "*localhost:$port*" } |
      Select-Object -First 1
if ($eg -and $eg.MainWindowHandle -ne 0) {
    Add-Type -AssemblyName Microsoft.VisualBasic
    [Microsoft.VisualBasic.Interaction]::AppActivate($eg.Id)
    exit 0
}

# Show a loading window immediately so the user sees feedback right away.
# A background runspace handles the blocking HTTP poll so the UI stays responsive.
# The timer closes the form as soon as the API responds (or after 90 s timeout).
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = "PIE Manager"
$form.Size = "380,110"
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true

$label = New-Object System.Windows.Forms.Label
$label.Location = "20,15"
$label.Size = "340,20"
$label.Text = "PIE Manager is starting, please wait..."
$label.Font = New-Object System.Drawing.Font("Segoe UI", 10)
$form.Controls.Add($label)

$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Location = "20,45"
$bar.Size = "330,22"
$bar.Style = "Marquee"
$bar.MarqueeAnimationSpeed = 30
$form.Controls.Add($bar)

# Shared state between UI thread and background poll runspace
$state = [hashtable]::Synchronized(@{ Done = $false })

# Background runspace: polls the API without blocking the UI event loop
$rs = [System.Management.Automation.Runspaces.RunspaceFactory]::CreateRunspace()
$rs.Open()
$rs.SessionStateProxy.SetVariable('state', $state)
$rs.SessionStateProxy.SetVariable('url', $url)
$ps = [System.Management.Automation.PowerShell]::Create()
$ps.Runspace = $rs
[void]$ps.AddScript({
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest -Uri "$url/api/admin/version" -TimeoutSec 1 -UseBasicParsing -EA Stop | Out-Null
            $state.Done = $true
            return
        } catch { Start-Sleep 1 }
    }
    $state.Done = $true
})
$async = $ps.BeginInvoke()

# Timer: check every 500 ms if poll completed, then close the loading window
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 500
$timer.Add_Tick({
    if ($state.Done) {
        $timer.Stop()
        $form.Close()
    }
})
$timer.Start()

$form.ShowDialog() | Out-Null

$ps.EndInvoke($async) | Out-Null
$rs.Close()

# Open Edge in app mode (no address bar), fallback to default browser
$edgePaths = @(
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)
$edge = $edgePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($edge) { Start-Process $edge "--app=$url", "--window-size=1400,900" }
else        { Start-Process $url }
`
	os.WriteFile(launcherPath, []byte(launcherContent), 0644) //nolint:errcheck

	icoPath := filepath.Join(target, "pie-manager.ico")
	os.WriteFile(icoPath, iconICO, 0644) //nolint:errcheck

	// open-app.vbs: launches launcher.ps1 via wscript so no console window appears
	vbsLauncherPath := filepath.Join(target, "open-app.vbs")
	vbsLauncherContent := fmt.Sprintf(
		`CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""%s""", 0, False`,
		launcherPath)
	os.WriteFile(vbsLauncherPath, []byte(vbsLauncherContent), 0644) //nolint:errcheck

	// Start Menu shortcut → wscript.exe open-app.vbs
	startMenu := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs")
	shortcutPath := filepath.Join(startMenu, "PIE Manager.lnk")
	psShortcut := fmt.Sprintf(`
$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut('%s')
$s.TargetPath   = 'wscript.exe'
$s.Arguments    = '/B /NoLogo "%s"'
$s.IconLocation = '%s,0'
$s.Description  = 'PIE Manager — Portfolio Tracker'
$s.Save()`, shortcutPath, vbsLauncherPath, icoPath)
	if _, err := runPS(psShortcut); err != nil {
		logMessage(fmt.Sprintf("WARN: could not create shortcut: %v", err))
	} else {
		logMessage("OK: Start Menu shortcut created")
	}

	popup("Succès",
		"PIE Manager est installé et démarré.\nUtilisez le raccourci 'PIE Manager' dans le menu Démarrer.")

	logMessage("=== END ===")
	os.Exit(0)
}
