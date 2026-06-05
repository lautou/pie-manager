//go:build linux

package main

import (
	_ "embed"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

//go:embed assets/compose-prod.yaml
var composeProd []byte

//go:embed assets/haproxy.cfg
var haproxyCfg []byte

//go:embed assets/pie-manager.desktop
var desktopEntry []byte

//go:embed assets/pie-manager.svg
var iconSVG []byte

//go:embed assets/wrapper.py
var wrapperPy []byte

const installDir = ".local/share/pie-manager"

func runInstall() {
	fmt.Printf("=== PIE Manager %s — Installation ===\n\n", Version)

	if _, err := exec.LookPath("podman"); err != nil {
		fmt.Println("Podman not found.")
		fmt.Println("\nInstall Podman: sudo dnf install -y podman podman-compose")
		os.Exit(1)
	}
	fmt.Println("Podman OK")

	home := os.Getenv("HOME")
	target := filepath.Join(home, installDir)
	fmt.Printf("Install directory: %s\n", target)

	existingVersion := readInstalledVersion(target)
	if existingVersion != "" && existingVersion != Version {
		fmt.Printf("Updating: %s → %s\n\n", existingVersion, Version)
		fmt.Println("⚠  Backup recommended before upgrading.")
		fmt.Println("   Open PIE Manager → Administration système → Télécharger une sauvegarde")
		fmt.Print("   Press Enter when done (or Ctrl+C to cancel)...")
		fmt.Scanln()
	}

	composeCmd := detectComposeCmd()
	fmt.Printf("Compose: %s\n", composeCmd)

	// Pull images — skip if already present.
	// On upgrade: if a pull fails, warn and keep the previous APP_VERSION.
	containerVersion := Version
	images := []string{
		"quay.io/ltourreau/pie-manager-backend:" + Version,
		"quay.io/ltourreau/pie-manager-frontend:" + Version,
		"docker.io/library/postgres:16-alpine",
		"docker.io/library/redis:7-alpine",
		"docker.io/library/haproxy:alpine",
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

	fmt.Print("Installing files... ")
	if err := os.MkdirAll(target, 0755); err != nil {
		fmt.Printf("ERROR: %v\n", err)
		os.Exit(1)
	}

	if err := os.WriteFile(filepath.Join(target, "compose-prod.yaml"), composeProd, 0644); err != nil {
		fmt.Printf("ERROR: %v\n", err)
		os.Exit(1)
	}

	if err := os.WriteFile(filepath.Join(target, "VERSION"), []byte(Version+"\n"), 0644); err != nil {
		fmt.Printf("ERROR: %v\n", err)
		os.Exit(1)
	}

	port := readAppPort(target)
	if port == defaultPort {
		port = findAvailablePort(defaultPort)
		if port != defaultPort {
			fmt.Printf("  Port %d in use, using %d instead.\n", defaultPort, port)
		}
	}

	envContent := fmt.Sprintf("APP_VERSION=%s\nINSTALLER_VERSION=%s\nAPP_PORT=%d\n",
		containerVersion, Version, port)
	if err := os.WriteFile(filepath.Join(target, ".env"), []byte(envContent), 0644); err != nil {
		fmt.Printf("ERROR writing .env: %v\n", err)
		os.Exit(1)
	}

	if err := os.WriteFile(filepath.Join(target, "haproxy.cfg"), haproxyCfg, 0644); err != nil {
		fmt.Printf("ERROR writing haproxy.cfg: %v\n", err)
		os.Exit(1)
	}

	// Copy the binary itself (rename+write to avoid "text file busy").
	selfPath, _ := os.Executable()
	destBinary := filepath.Join(target, "pie-manager")
	selfResolved, _ := filepath.EvalSymlinks(selfPath)
	destResolved, _ := filepath.EvalSymlinks(destBinary)
	if selfResolved != destResolved {
		os.Rename(destBinary, destBinary+".old")
		if err := copyFile(selfPath, destBinary, 0755); err != nil {
			os.Rename(destBinary+".old", destBinary)
			fmt.Printf("ERROR copying binary: %v\n", err)
			os.Exit(1)
		}
		os.Remove(destBinary + ".old")
	}

	fmt.Println("OK")

	localBin := filepath.Join(home, ".local/bin")
	os.MkdirAll(localBin, 0755)
	symlink := filepath.Join(localBin, "pie-manager")
	os.Remove(symlink)
	os.Symlink(destBinary, symlink)

	fmt.Print("Desktop integration... ")
	hasWebKit := deployWrapper(target)
	installDesktopAndIcon(home, target, hasWebKit)
	fmt.Println("OK")

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
	dir := filepath.Dir(composePath)
	parts := strings.Fields(composeCmd)

	down := exec.Command(parts[0], append(parts[1:], "-f", composePath, "down", "--remove-orphans")...)
	down.Dir = dir
	down.Stdout = io.Discard
	down.Stderr = io.Discard
	down.Run() //nolint:errcheck

	up := exec.Command(parts[0], append(parts[1:], "-f", composePath, "up", "-d")...)
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
	execLine := fmt.Sprintf("Exec=%s start", filepath.Join(target, "pie-manager"))
	desktopContent := strings.ReplaceAll(
		string(desktopEntry),
		"Exec=/opt/pie-manager/lancer.sh",
		execLine,
	)

	appDir := filepath.Join(home, ".local/share/applications")
	os.MkdirAll(appDir, 0755)
	os.WriteFile(filepath.Join(appDir, "pie-manager.desktop"), []byte(desktopContent), 0644)

	iconDir := filepath.Join(home, ".local/share/icons/hicolor/scalable/apps")
	os.MkdirAll(iconDir, 0755)
	os.WriteFile(filepath.Join(iconDir, "pie-manager.svg"), iconSVG, 0644)

	pngDir := filepath.Join(home, ".local/share/icons/hicolor/64x64/apps")
	os.MkdirAll(pngDir, 0755)
	pngPath := filepath.Join(pngDir, "pie-manager.png")
	svgPath := filepath.Join(iconDir, "pie-manager.svg")
	if _, err := exec.LookPath("rsvg-convert"); err == nil {
		exec.Command("rsvg-convert", "-w", "64", "-h", "64", svgPath, "-o", pngPath).Run()
	}

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
