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
	"strings"
	"syscall"
	"time"
)

//go:embed assets/compose-prod.yaml
var composeProd []byte

//go:embed assets/haproxy.cfg
var haproxyCfg []byte

//go:embed assets/launcher.exe
var launcherExe []byte

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

// enableWindowsFeature enables a Windows optional feature via DISM.
// Idempotent — safe to call even if the feature is already enabled.
func enableWindowsFeature(name string) error {
	_, err := runPS(fmt.Sprintf(
		`Enable-WindowsOptionalFeature -Online -FeatureName %s -All -NoRestart -ErrorAction Stop`, name))
	return err
}

// isWingetAvailable reports whether winget is resolvable on PATH.
func isWingetAvailable() bool {
	_, err := exec.LookPath("winget")
	return err == nil
}

// addAppxPackage installs a local package file for the current user via
// Add-AppxPackage — the standard, documented way to sideload these packages
// (WSL, winget, VCLibs, UI.Xaml) when run as an elevated interactive user,
// which is how this installer is actually launched (UAC, not a service
// account). run() is used so any failure carries the command's combined
// output in the returned error (unlike the streamed-to-console exec.Command
// calls elsewhere in this file).
//
// NOT Add-AppxProvisionedPackage: that cmdlet requires the package to pass
// an internal "IsStagedPackageStoreSigned" check, which the WSL msixbundle
// happens to satisfy but VCLibs's plain sideload .appx does not (confirmed
// live via C:\Windows\Logs\DISM\dism.log: "Failed while checking
// IsStagedPackageStoreSigned" → HRESULT 0x80070490) — provisioning is built
// for machine-wide staging of Store-packaged content, not for sideloading
// arbitrary redistributable framework packages like this installer needs.
//
// A failure is swallowed when it matches isAppxAlreadyNewerError — see that
// function's comment (confirmed live on a real Windows 11 VM, elevated
// non-SYSTEM user: this exact case hit for Microsoft.UI.Xaml).
func addAppxPackage(path string) error {
	err := run("powershell", "-NoProfile", "-NonInteractive", "-Command",
		fmt.Sprintf(`Add-AppxPackage -Path "%s"`, path))
	if err != nil && isAppxAlreadyNewerError(err.Error()) {
		return nil
	}
	return err
}

// installWSLFromGitHub downloads and installs the official WSL package
// directly from Microsoft's GitHub releases, bypassing the Microsoft Store.
// This is Microsoft's own documented fallback for machines where the Store
// isn't provisioned (e.g. a fresh local-account Windows install) — see
// https://github.com/microsoft/WSL/releases and
// https://learn.microsoft.com/en-us/windows/wsl/install-manual.
func installWSLFromGitHub() error {
	url, err := githubLatestAssetURL("microsoft/WSL", "_x64_ARM64.msixbundle")
	if err != nil {
		return fmt.Errorf("resolving WSL package URL: %w", err)
	}
	dest := filepath.Join(os.TempDir(), "pie-manager-wsl.msixbundle")
	if err := downloadFile(url, dest); err != nil {
		return fmt.Errorf("downloading WSL package: %w", err)
	}
	defer os.Remove(dest)
	if err := addAppxPackage(dest); err != nil {
		return fmt.Errorf("installing WSL package: %w", err)
	}
	return nil
}

const uiXamlNuGetVersion = "2.8.6"
const uiXamlAppxSuffix = "tools/AppX/x64/Release/Microsoft.UI.Xaml.2.8.appx"

// installWingetFromGitHub installs winget (App Installer) and its two
// required framework dependencies directly from Microsoft's official
// distribution channels, bypassing the Microsoft Store — see
// https://github.com/microsoft/winget-cli/releases and
// https://learn.microsoft.com/en-us/windows/package-manager/winget/.
func installWingetFromGitHub() error {
	tmp := os.TempDir()

	// 1. Microsoft.VCLibs — stable Microsoft-hosted direct link.
	vclibs := filepath.Join(tmp, "pie-manager-vclibs.appx")
	if err := downloadFile("https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx", vclibs); err != nil {
		return fmt.Errorf("downloading VCLibs: %w", err)
	}
	defer os.Remove(vclibs)
	if err := addAppxPackage(vclibs); err != nil {
		return fmt.Errorf("installing VCLibs: %w", err)
	}

	// 2. Microsoft.UI.Xaml — only distributed via NuGet, no direct appx download exists.
	nupkg := filepath.Join(tmp, "pie-manager-ui-xaml.nupkg")
	nupkgURL := fmt.Sprintf("https://www.nuget.org/api/v2/package/Microsoft.UI.Xaml/%s", uiXamlNuGetVersion)
	if err := downloadFile(nupkgURL, nupkg); err != nil {
		return fmt.Errorf("downloading Microsoft.UI.Xaml: %w", err)
	}
	defer os.Remove(nupkg)
	xamlAppx := filepath.Join(tmp, "pie-manager-ui-xaml.appx")
	if err := extractZipEntryBySuffix(nupkg, uiXamlAppxSuffix, xamlAppx); err != nil {
		return fmt.Errorf("extracting Microsoft.UI.Xaml: %w", err)
	}
	defer os.Remove(xamlAppx)
	if err := addAppxPackage(xamlAppx); err != nil {
		return fmt.Errorf("installing Microsoft.UI.Xaml: %w", err)
	}

	// 3. winget itself.
	url, err := githubLatestAssetURL("microsoft/winget-cli", "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle")
	if err != nil {
		return fmt.Errorf("resolving winget package URL: %w", err)
	}
	dest := filepath.Join(tmp, "pie-manager-winget.msixbundle")
	if err := downloadFile(url, dest); err != nil {
		return fmt.Errorf("downloading winget: %w", err)
	}
	defer os.Remove(dest)
	if err := addAppxPackage(dest); err != nil {
		return fmt.Errorf("installing winget: %w", err)
	}
	return nil
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
		// Enable the two required optional features ourselves first. wsl
		// --install is supposed to do this too, but on a fresh local-account
		// Windows install (Microsoft Store never provisioned) it can fail
		// before even reaching this step. Doing it directly via DISM removes
		// that dependency; it's idempotent and harmless if already enabled.
		enableWindowsFeature("Microsoft-Windows-Subsystem-Linux") //nolint:errcheck — best-effort, wsl --install retries this too
		enableWindowsFeature("VirtualMachinePlatform")            //nolint:errcheck

		logMessage("INFO: running wsl --install --no-distribution...")
		wsl := exec.Command("wsl", "--install", "--no-distribution")
		wsl.Stdout = os.Stdout
		wsl.Stderr = os.Stderr
		if err := wsl.Run(); err != nil {
			logMessage(fmt.Sprintf("WARN: wsl --install failed (%v) — Microsoft Store may be unavailable, falling back to direct install from GitHub", err))
			if fbErr := installWSLFromGitHub(); fbErr != nil {
				logMessage(fmt.Sprintf("FATAL: WSL2 install failed (Store method and GitHub fallback both failed): %v", fbErr))
				popup("Erreur", fmt.Sprintf("L'installation de WSL2 a échoué.\nConsultez le fichier journal :\n%s", logFilePath))
				os.Exit(1)
			}
			logMessage("OK: WSL2 installed via GitHub fallback (Microsoft Store unavailable)")
		} else {
			logMessage("OK: WSL2 install succeeded")
		}
		systemChanged = true
	}

	// ── winget ───────────────────────────────────────────────────────────────
	// Bootstrap winget itself if missing, before the Podman CLI/Docker Compose
	// steps below (both depend on it). Same root cause as the WSL2 fallback
	// above: a fresh local-account Windows install may never have provisioned
	// the Microsoft Store, and winget is normally provisioned through it.
	if !isWingetAvailable() {
		fmt.Println("=== PIE Manager — Installation de winget ===")
		logMessage("WARN: winget not found — installing App Installer directly from GitHub (Microsoft Store unavailable or not provisioned)")
		if err := installWingetFromGitHub(); err != nil {
			logMessage(fmt.Sprintf("FATAL: could not install winget: %v", err))
			popup("Erreur", fmt.Sprintf("winget est introuvable et son installation de secours a échoué.\nConsultez le fichier journal :\n%s", logFilePath))
			os.Exit(1)
		}
		logMessage("OK: winget installed via GitHub fallback")
		refreshPath()
		logMessage("INFO: PATH refreshed from registry")
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
		// The RunOnce key isn't guaranteed to exist on every profile (confirmed
		// live: Set-ItemProperty alone failed with "PathNotFound" on a fresh
		// local account) — New-Item -Force creates it if missing, no-ops if not.
		runOnceCmd := fmt.Sprintf(`New-Item -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Force | Out-Null; Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "PIEManagerResume" -Value '"%s"'`, exePath)
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
	// systemctl --user enable fails silently in SSH context when the
	// default.target.wants/ directory is owned by root (Podman Machine default).
	// Reliable fix: create the symlink directly after fixing ownership.
	// loginctl enable-linger allows user services to survive without a login session.
	fmt.Println("=== PIE Manager — Activation du redémarrage automatique des containers ===")
	logMessage("INFO: configuring podman-restart.service inside Podman Machine...")
	setupCmd := `sudo loginctl enable-linger $USER && ` +
		`mkdir -p ~/.config/systemd/user/default.target.wants && ` +
		`sudo chown -R $USER:$USER ~/.config && ` +
		`ln -sf /usr/lib/systemd/user/podman-restart.service ` +
		`~/.config/systemd/user/default.target.wants/podman-restart.service && ` +
		`XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload`
	// Passed as the sole trailing argument, not split as "bash", "-c", setupCmd —
	// podman machine ssh re-joins multiple trailing args before forwarding over
	// SSH and mangles compound commands with && (containers/podman#13517); the
	// remote SSH server already wraps a single command string in a shell itself.
	if err := run("podman", "machine", "ssh", "--", setupCmd); err != nil {
		logMessage(fmt.Sprintf("WARN: could not configure podman-restart.service: %v", err))
	} else {
		logMessage("OK: podman-restart.service enabled via symlink — containers will auto-restart at machine start")
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
	os.WriteFile(filepath.Join(target, "haproxy.cfg"), haproxyCfg, 0644)        //nolint:errcheck

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
	port = readAppPort(target)
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

	// Remove old PIE Manager image versions — only our own images, never
	// images from other Podman projects on the same machine.
	logMessage("INFO: removing old PIE Manager image versions...")
	for _, repo := range []string{
		"quay.io/ltourreau/pie-manager-backend",
		"quay.io/ltourreau/pie-manager-frontend",
	} {
		cmd := exec.Command("podman", "images", repo, "--format", "{{.Tag}}")
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
		out, err := cmd.Output()
		if err != nil {
			continue
		}
		for _, tag := range strings.Split(strings.TrimSpace(string(out)), "\n") {
			if tag != "" && tag != Version && tag != "latest" {
				rmi := exec.Command("podman", "rmi", repo+":"+tag)
				rmi.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
				rmi.Run() //nolint:errcheck
			}
		}
	}
	logMessage("OK: old image versions removed")

	// ── Auto-start at login (Task Scheduler + wscript invisible launcher) ────────
	// wscript.exe is a GUI-subsystem binary — it never creates a console window,
	// unlike powershell.exe which flashes a window even with -WindowStyle Hidden.
	// The .vbs script passes SW_HIDE (0) to WshShell.Run so podman starts fully
	// invisible. -Force makes the task registration idempotent.
	logMessage("INFO: registering auto-start task via Task Scheduler (wscript method)...")

	vbsPath := filepath.Join(target, "start-podman.vbs")
	// Retry loop: WSL2 may not be ready immediately at login.
	// True = wait for each attempt; retries up to 5 times with 5s between attempts.
	vbsContent := `Dim sh : Set sh = CreateObject("WScript.Shell")
Dim i : i = 0
Do While i < 5
    If sh.Run("podman machine start", 0, True) = 0 Then Exit Do
    WScript.Sleep 5000
    i = i + 1
Loop`
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
	// launcher.exe : native Go + WebView2 binary with the PIE Manager icon
	// embedded as a Windows PE resource. Handles single-instance detection,
	// polls until the backend is ready, then shows the app in a WebView2 window.
	// Windows extracts the icon from the .exe automatically — no IconLocation needed.
	fmt.Println("=== PIE Manager — Intégration bureau ===")
	logMessage("INFO: deploying launcher.exe and desktop shortcut...")

	// Deploy launcher.exe — the WebView2 native Go launcher with embedded icon.
	launcherExePath := filepath.Join(target, "launcher.exe")
	if err := os.WriteFile(launcherExePath, launcherExe, 0755); err != nil {
		logMessage(fmt.Sprintf("WARN: could not write launcher.exe: %v", err))
	} else {
		logMessage("OK: launcher.exe deployed to " + launcherExePath)
	}

	// Start Menu shortcut → launcher.exe directly.
	// Windows extracts the taskbar/Start Menu icon from the .exe PE resources —
	// no IconLocation needed on the shortcut.
	startMenu := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs")
	shortcutPath := filepath.Join(startMenu, "PIE Manager.lnk")
	psShortcut := fmt.Sprintf(`
$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut('%s')
$s.TargetPath  = '%s'
$s.Description = 'PIE Manager — Portfolio Tracker'
$s.Save()`, shortcutPath, launcherExePath)
	if _, err := runPS(psShortcut); err != nil {
		logMessage(fmt.Sprintf("WARN: could not create shortcut: %v", err))
	} else {
		logMessage("OK: Start Menu shortcut created")
	}

	popup("Succès",
		"PIE Manager est installé et démarré.\nUtilisez le raccourci 'PIE Manager' dans le menu Démarrer.")

	logMessage("=== END ===")
}
