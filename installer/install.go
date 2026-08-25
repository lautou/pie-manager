//go:build linux

// SPDX-License-Identifier: AGPL-3.0-or-later

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

	performInstall(home, target,
		func() error { return nil },
		func(home, target string) {
			fmt.Print("Desktop integration... ")
			deployWrapper(target)
			installDesktopAndIcon(home, target)
			fmt.Println("OK")
		},
		"Launch via the GNOME icon or: pie-manager start",
	)
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

func installDesktopAndIcon(home, target string) {
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

