package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
)

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

func isPodmanMachineRunning() bool {
	cmd := exec.Command("podman", "machine", "list", "--format", "{{.LastUp}}")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	out, err := cmd.Output()
	return err == nil && strings.Contains(strings.ToLower(string(out)), "running")
}

func isPodmanMachineInitialized() bool {
	cmd := exec.Command("podman", "machine", "list", "--format", "{{.Name}}")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	out, err := cmd.Output()
	return err == nil && strings.TrimSpace(string(out)) != ""
}

func isPodmanInstalled() bool {
	cmd := exec.Command("winget", "list", "--id", "RedHat.Podman")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: noWindow}
	return cmd.Run() == nil
}

func rebootPending() bool {
	out, err := runPS(`(Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending").ToString()`)
	return err == nil && strings.EqualFold(out, "True")
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
			popup("Erreur étape 3", fmt.Sprintf("L'initialisation de la machine Podman a échoué.\nConsultez le fichier journal :\n%s", logFilePath))
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

	// ── Auto-start at login (Task Scheduler) ──────────────────────────────────
	// Registers a hidden task that runs `podman machine start` at every user
	// login. -Force makes it idempotent — safe to call on every installer run.
	logMessage("INFO: registering auto-start task via Task Scheduler...")
	autoStart := `Register-ScheduledTask ` +
		`-TaskName "PIEManager - Start Podman Machine" ` +
		`-Action (New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command 'podman machine start'") ` +
		`-Trigger (New-ScheduledTaskTrigger -AtLogOn) ` +
		`-Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)) ` +
		`-Force | Out-Null`
	if _, err := runPS(autoStart); err != nil {
		logMessage(fmt.Sprintf("WARN: could not register auto-start task: %v", err))
	} else {
		logMessage("OK: auto-start task registered (hidden, at login)")
	}

	popup("Succès",
		"WSL2, Podman CLI et la machine Podman sont prêts.\nVous pouvez maintenant installer PIE Manager.")

	logMessage("=== END ===")
	os.Exit(0)
}
