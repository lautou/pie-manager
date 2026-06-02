package main

import (
	_ "embed"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

//go:embed assets/compose-prod.yaml
var composeProd []byte

//go:embed assets/nginx.conf
var nginxConf []byte

//go:embed assets/pie-manager.desktop
var desktopEntry []byte

//go:embed assets/pie-manager.svg
var iconSVG []byte

//go:embed assets/wrapper.py
var wrapperPy []byte

//go:embed assets/pie-manager.ico
var iconICO []byte

//go:embed assets/launcher.ps1
var launcherPS1 []byte

const defaultPort = 14943

// findAvailablePort returns the first free TCP port starting from start.
func findAvailablePort(start int) int {
	for port := start; port < 65535; port++ {
		ln, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
		if err == nil {
			ln.Close()
			return port
		}
	}
	return start
}

const installDir = ".local/share/pie-manager"

func runInstall() {
	// On Windows: always wait for Enter before exiting so the console window
	// stays open long enough for the user to read any error messages.
	if runtime.GOOS == "windows" {
		defer func() {
			fmt.Print("\nPress Enter to close this window...")
			fmt.Scanln()
		}()
	}

	fmt.Printf("=== PIE Manager %s — Installation ===\n\n", Version)

	if runtime.GOOS != "linux" && runtime.GOOS != "windows" {
		fmt.Println("ERROR: only Linux and Windows are supported.")
		os.Exit(1)
	}

	home := os.Getenv("HOME")
	target := filepath.Join(home, installDir)
	if runtime.GOOS == "windows" {
		target = windowsInstallDir()
	}
	fmt.Printf("Install directory: %s\n", target)

	// Check for existing installation — always update config files.
	existingVersion := readInstalledVersion(target)
	if existingVersion != "" && existingVersion != Version {
		fmt.Printf("Updating: %s → %s\n\n", existingVersion, Version)
		fmt.Println("⚠  Backup recommended before upgrading.")
		fmt.Println("   Open PIE Manager → Administration système → Télécharger une sauvegarde")
		fmt.Print("   Press Enter when done (or Ctrl+C to cancel)...")
		fmt.Scanln()
	}

	if runtime.GOOS == "windows" {
		// On Windows: check WSL2 first. If missing, install both WSL2 + Podman CLI
		// before the reboot so only one reboot is needed instead of two.
		fmt.Print("Checking WSL2... ")
		if !checkWSL2() {
			fmt.Println("not found.")
			installWSL2andPodman()
			os.Exit(0) // exit cleanly — user re-runs after reboot (if required)
		}
		fmt.Println("OK")

		fmt.Print("Checking Podman... ")
		if !checkPodmanWindows() {
			fmt.Println("not found.")
			if err := installPodmanWindows(); err != nil {
				fmt.Println("Could not install Podman automatically.")
				fmt.Println("Install manually: https://podman-desktop.io")
				os.Exit(1)
			}
		}
		fmt.Println("OK")
	} else {
		fmt.Print("Checking Podman... ")
		if _, err := exec.LookPath("podman"); err != nil {
			fmt.Println("not found.")
			fmt.Println("\nInstall Podman: sudo dnf install -y podman podman-compose")
			os.Exit(1)
		}
		fmt.Println("OK")
	}

	// On Windows, ensure Podman Machine is running and podman-compose is installed inside it
	if runtime.GOOS == "windows" {
		ensurePodmanMachineRunning()
		installPodmanComposeInMachine() // idempotent — skips if already installed
	}

	// Check for podman-compose
	composeCmd := detectComposeCmd()
	fmt.Printf("Compose : %s\n", composeCmd)

	// Pull images — skip pull if image already present locally.
	// Images are public on ghcr.io — no authentication required.
	// On upgrade: if a pull fails (e.g. 403 for an installer-only release that
	// has no new container images), warn and keep the previous APP_VERSION so
	// the running containers are not broken. The installer binary is still updated.
	containerVersion := Version // version to write into .env
	images := []string{
		"ghcr.io/lautou/pie-manager-backend:" + Version,
		"ghcr.io/lautou/pie-manager-frontend:" + Version,
		"postgres:16-alpine",
		"redis:7-alpine",
		"nginx:alpine",
	}
	for _, img := range images {
		if podmanImageExists(img) {
			fmt.Printf("Image %s... already present, skipping pull.\n", img)
			continue
		}
		fmt.Printf("Pulling %s... ", img)
		cmd := exec.Command("podman", "pull", img)
		cmd.Stdout = io.Discard
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			if existingVersion != "" {
				// Upgrade: keep existing container images — only the installer binary is updated.
				fmt.Printf("\nWARNING: Could not pull %s (%v)\n", img, err)
				fmt.Printf("  Container images will remain at v%s.\n", existingVersion)
				fmt.Println("  The installer binary has been updated to " + Version + ".")
				containerVersion = existingVersion
				break
			}
			fmt.Printf("ERROR: %v\n", err)
			os.Exit(1)
		}
		fmt.Println("OK")
	}

	// Create installation directory
	fmt.Print("Installing files... ")
	if err := os.MkdirAll(target, 0755); err != nil {
		fmt.Printf("ERROR: %v\n", err)
		os.Exit(1)
	}

	// Write compose-prod.yaml
	if err := os.WriteFile(filepath.Join(target, "compose-prod.yaml"), composeProd, 0644); err != nil {
		fmt.Printf("ERROR: %v\n", err)
		os.Exit(1)
	}

	// Write VERSION
	if err := os.WriteFile(filepath.Join(target, "VERSION"), []byte(Version+"\n"), 0644); err != nil {
		fmt.Printf("ERROR: %v\n", err)
		os.Exit(1)
	}

	// Preserve existing port if already configured, otherwise find a free one.
	// This ensures reinstalls/upgrades keep the same port the user is used to.
	port := readAppPort(target)
	if port == defaultPort {
		port = findAvailablePort(defaultPort)
		if port != defaultPort {
			fmt.Printf("  Port %d in use, using %d instead.\n", defaultPort, port)
		}
	}

	// Write .env for podman-compose.
	// APP_VERSION  = container image tag (may stay at previous version if pull failed)
	// INSTALLER_VERSION = this installer's version (always current — shown in the UI)
	envContent := fmt.Sprintf("APP_VERSION=%s\nINSTALLER_VERSION=%s\nAPP_PORT=%d\n",
		containerVersion, Version, port)
	if err := os.WriteFile(filepath.Join(target, ".env"), []byte(envContent), 0644); err != nil {
		fmt.Printf("ERROR writing .env: %v\n", err)
		os.Exit(1)
	}

	// Write nginx.conf
	if err := os.WriteFile(filepath.Join(target, "nginx.conf"), nginxConf, 0644); err != nil {
		fmt.Printf("ERROR writing nginx.conf: %v\n", err)
		os.Exit(1)
	}

	// Copy the binary itself
	// Use rename+write to avoid "text file busy" when running from target dir
	selfPath, _ := os.Executable()
	binaryName := "pie-manager"
	if runtime.GOOS == "windows" {
		binaryName = "pie-manager.exe"
	}
	destBinary := filepath.Join(target, binaryName)
	selfResolved, _ := filepath.EvalSymlinks(selfPath)
	destResolved, _ := filepath.EvalSymlinks(destBinary)
	if selfResolved != destResolved {
		// Rename old binary (kernel keeps inode open), write new one
		os.Rename(destBinary, destBinary+".old")
		if err := copyFile(selfPath, destBinary, 0755); err != nil {
			os.Rename(destBinary+".old", destBinary) // rollback
			fmt.Printf("ERROR copying binary: %v\n", err)
			os.Exit(1)
		}
		os.Remove(destBinary + ".old")
	}

	fmt.Println("OK")

	// Create symlink in ~/.local/bin/ for command-line use
	localBin := filepath.Join(home, ".local/bin")
	os.MkdirAll(localBin, 0755)
	symlink := filepath.Join(localBin, "pie-manager")
	os.Remove(symlink)
	os.Symlink(destBinary, symlink)


	// Write ICO icon and launcher script for Windows shortcut
	if runtime.GOOS == "windows" {
		os.WriteFile(filepath.Join(target, "pie-manager.ico"), iconICO, 0644)          //nolint:errcheck
		os.WriteFile(filepath.Join(target, "launcher.ps1"), launcherPS1, 0644)         //nolint:errcheck
	}

	// Desktop integration
	fmt.Print("Desktop integration... ")
	if runtime.GOOS == "windows" {
		icoPath := filepath.Join(target, "pie-manager.ico")
		launcherPath := filepath.Join(target, "launcher.ps1")
		createWindowsShortcut(launcherPath, "PIE Manager", icoPath)
	} else {
		hasWebKit := deployWrapper(target)
		installDesktopAndIcon(home, target, hasWebKit)
	}
	fmt.Println("OK")

	// Start with force-recreate to apply new images
	fmt.Println("\nStarting services...")
	forceRecreate(composeCmd, filepath.Join(target, "compose-prod.yaml"))

	fmt.Printf("\n✓ PIE Manager %s installed successfully!\n", Version)
	fmt.Println("  Launch via the GNOME icon or: pie-manager start")
}

func readInstalledVersion(target string) string {
	data, err := os.ReadFile(filepath.Join(target, "VERSION"))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

func detectComposeCmd() string {
	if _, err := exec.LookPath("podman-compose"); err == nil {
		return "podman-compose"
	}
	return "podman compose"
}

func forceRecreate(composeCmd, composePath string) {
	if runtime.GOOS == "windows" {
		// On Windows: run compose inside the Podman Machine via SSH.
		// Use `podman compose` (built-in to the Podman binary in the VM) — more
		// reliable than the pip-installed podman-compose which may not be present.
		wslPath := wslComposePath(composePath)
		exec.Command("podman", "machine", "ssh", "--",
			"podman", "compose", "-f", wslPath, "down", "--remove-orphans").Run() //nolint:errcheck
		up := exec.Command("podman", "machine", "ssh", "--",
			"podman", "compose", "-f", wslPath, "up", "-d")
		up.Stdout = io.Discard
		up.Stderr = os.Stderr
		up.Run() //nolint:errcheck
		return
	}

	dir := filepath.Dir(composePath)
	parts := strings.Fields(composeCmd)

	// Stop and remove existing containers first to avoid reconciliation errors
	// when the compose file has changed (e.g. new services added like nginx).
	downArgs := append(parts[1:], "-f", composePath, "down", "--remove-orphans")
	down := exec.Command(parts[0], downArgs...)
	down.Dir = dir
	down.Stdout = io.Discard
	down.Stderr = io.Discard
	down.Run() //nolint:errcheck

	upArgs := append(parts[1:], "-f", composePath, "up", "-d")
	up := exec.Command(parts[0], upArgs...)
	up.Dir = dir
	up.Stdout = io.Discard
	up.Stderr = os.Stderr
	up.Run() //nolint:errcheck
}

// deployWrapper writes wrapper.py if WebKitGTK is available. Returns true on success.
func deployWrapper(target string) bool {
	check := exec.Command("python3", "-c",
		"import gi; gi.require_version('WebKit2', '4.1'); from gi.repository import WebKit2")
	check.Stdout = io.Discard
	check.Stderr = io.Discard
	if check.Run() != nil {
		return false
	}
	wrapperPath := filepath.Join(target, "wrapper.py")
	if err := os.WriteFile(wrapperPath, wrapperPy, 0755); err != nil {
		return false
	}
	return true
}

func installDesktopAndIcon(home, target string, _ bool) {
	// Always use pie-manager start as the Exec — it starts containers if needed,
	// then opens the WebKitGTK wrapper (or browser fallback). This ensures the
	// GNOME icon works correctly after a reboot even if containers are stopped.
	execLine := fmt.Sprintf("Exec=%s start", filepath.Join(target, "pie-manager"))
	desktopContent := strings.ReplaceAll(
		string(desktopEntry),
		"Exec=/opt/pie-manager/lancer.sh",
		execLine,
	)

	appDir := filepath.Join(home, ".local/share/applications")
	os.MkdirAll(appDir, 0755)
	os.WriteFile(filepath.Join(appDir, "pie-manager.desktop"), []byte(desktopContent), 0644)

	// SVG icon
	iconDir := filepath.Join(home, ".local/share/icons/hicolor/scalable/apps")
	os.MkdirAll(iconDir, 0755)
	os.WriteFile(filepath.Join(iconDir, "pie-manager.svg"), iconSVG, 0644)

	// Convert SVG to PNG if rsvg-convert is available
	pngDir := filepath.Join(home, ".local/share/icons/hicolor/64x64/apps")
	os.MkdirAll(pngDir, 0755)
	pngPath := filepath.Join(pngDir, "pie-manager.png")
	svgPath := filepath.Join(iconDir, "pie-manager.svg")
	if _, err := exec.LookPath("rsvg-convert"); err == nil {
		exec.Command("rsvg-convert", "-w", "64", "-h", "64", svgPath, "-o", pngPath).Run()
	}

	// Refresh GNOME icon cache (best-effort)
	exec.Command("update-desktop-database", filepath.Join(home, ".local/share/applications")).Run()
	exec.Command("gtk-update-icon-cache", "-f", filepath.Join(home, ".local/share/icons/hicolor")).Run()
}


func copyFile(src, dst string, perm os.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, perm)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}
