//go:build darwin

package main

import (
	_ "embed"
	"encoding/json"
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

//go:embed assets/pie-manager-macos-info.plist
var appInfoPlistTemplate string

// installDir mirrors Linux's XDG-style per-user data directory convention,
// using macOS's own idiomatic per-user application-support location instead.
const installDir = "Library/Application Support/PieManager"

const appBundleName = "PIE Manager.app"

const launchAgentLabel = "com.pie-manager.podman-start"

func runInstall() {
	fmt.Printf("=== PIE Manager %s — Installation ===\n\n", Version)

	if _, err := exec.LookPath("podman"); err != nil {
		fmt.Println("Podman not found — installing automatically...")
		if err := installPodmanFromGitHub(); err != nil {
			fmt.Printf("ERROR: %v\n", err)
			fmt.Println("\nManual install: brew install podman (see https://brew.sh)")
			fmt.Println("Or download directly: https://github.com/containers/podman/releases/latest")
			os.Exit(1)
		}
		fmt.Println("Podman installed.")
	} else {
		fmt.Println("Podman OK")
	}

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

	if err := ensurePodmanMachine(); err != nil {
		fmt.Printf("ERROR: %v\n", err)
		os.Exit(1)
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

	fmt.Print("Configuring container auto-restart... ")
	configurePodmanRestartService()
	fmt.Println("OK")

	fmt.Print("Desktop integration... ")
	if err := installLaunchAgent(); err != nil {
		fmt.Printf("\nWARNING: could not install login auto-start: %v\n", err)
	}
	if err := installAppBundle(home, target); err != nil {
		fmt.Printf("\nWARNING: could not install the Applications shortcut: %v\n", err)
	}
	fmt.Println("OK")

	fmt.Println("\nStarting services...")
	forceRecreate(composeCmd, filepath.Join(target, "compose-prod.yaml"))

	// Remove old PIE Manager image versions — only our own images, never
	// images from other Podman projects on the same machine.
	fmt.Print("Removing old PIE Manager image versions... ")
	for _, repo := range []string{
		"quay.io/ltourreau/pie-manager-backend",
		"quay.io/ltourreau/pie-manager-frontend",
	} {
		out, err := exec.Command("podman", "images", repo, "--format", "{{.Tag}}").Output()
		if err != nil {
			continue
		}
		for _, tag := range strings.Split(strings.TrimSpace(string(out)), "\n") {
			if tag != "" && tag != Version && tag != "latest" {
				exec.Command("podman", "rmi", repo+":"+tag).Run() //nolint:errcheck
			}
		}
	}
	fmt.Println("OK")

	fmt.Printf("\n✓ PIE Manager %s installed successfully!\n", Version)
	fmt.Println("  Launch via \"PIE Manager\" in ~/Applications, or: pie-manager start")
}

// installPodmanFromGitHub downloads the official Podman installer package for
// macOS/arm64 from containers/podman's latest GitHub release and installs it
// via macOS's native `installer` CLI — the same "official package straight
// from GitHub, not a third-party package manager" pattern already used for
// WSL2/winget on Windows (see common.go's githubLatestAssetURL/downloadFile).
// Podman's own docs recommend this .pkg over Homebrew for exactly this reason
// (Homebrew is community-maintained; the .pkg is the vendor's own artifact).
// Only handles a fresh install (podman absent) — re-running the .pkg to
// *upgrade* an already-installed Podman is a known-fragile path upstream
// (podman-mac-helper conflicts) and is left to the user/Homebrew, not this
// installer's fresh-install path.
func installPodmanFromGitHub() error {
	url, err := githubLatestAssetURL("containers/podman", "macos-arm64.pkg")
	if err != nil {
		return fmt.Errorf("finding latest Podman release: %w", err)
	}

	pkgPath := filepath.Join(os.TempDir(), "podman-installer-macos-arm64.pkg")
	fmt.Println("Downloading Podman installer...")
	if err := downloadFile(url, pkgPath); err != nil {
		return fmt.Errorf("downloading Podman installer: %w", err)
	}
	defer os.Remove(pkgPath)

	fmt.Println("Installing Podman (administrator password required)...")
	cmd := exec.Command("sudo", "installer", "-pkg", pkgPath, "-target", "/")
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("installing Podman: %w", err)
	}
	return nil
}

// --- Podman Machine (macOS runs containers inside an Apple Hypervisor.framework VM) ---

type podmanMachineInfo struct {
	Name    string `json:"Name"`
	Running bool   `json:"Running"`
}

func listPodmanMachines() ([]podmanMachineInfo, error) {
	out, err := exec.Command("podman", "machine", "list", "--format", "json").Output()
	if err != nil {
		return nil, err
	}
	var machines []podmanMachineInfo
	if err := json.Unmarshal(out, &machines); err != nil {
		return nil, err
	}
	return machines, nil
}

func isPodmanMachineInitialized() bool {
	machines, err := listPodmanMachines()
	return err == nil && len(machines) > 0
}

func isPodmanMachineRunning() bool {
	machines, err := listPodmanMachines()
	if err != nil {
		return false
	}
	for _, m := range machines {
		if m.Running {
			return true
		}
	}
	return false
}

// ensurePodmanMachine initializes and/or starts the Podman machine if needed.
// Unlike Windows's WSL2 setup, this never requires a reboot or an OS-feature
// toggle — Apple's Hypervisor.framework is already part of the OS.
func ensurePodmanMachine() error {
	if !isPodmanMachineInitialized() {
		fmt.Println("Initializing Podman machine (first run, may take a minute)...")
		cmd := exec.Command("podman", "machine", "init")
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("podman machine init: %w", err)
		}
	}
	if !isPodmanMachineRunning() {
		fmt.Println("Starting Podman machine...")
		cmd := exec.Command("podman", "machine", "start")
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("podman machine start: %w", err)
		}
	}
	return nil
}

// configurePodmanRestartService symlinks podman-restart.service inside the
// Podman machine's guest (Fedora CoreOS, same as Windows's WSL2 guest) so
// containers come back up automatically after the machine restarts.
//
// The whole command is passed as the SOLE trailing argument after "--", never
// split as separate "bash"/"-c"/cmd arguments — `podman machine ssh` mangles
// a compound "&&"-chained command re-joined that way (confirmed independently:
// https://github.com/containers/podman/issues/13517), silently no-op'ing the
// setup. See CLAUDE.md's Windows gotchas for the original discovery.
func configurePodmanRestartService() {
	cmd := "sudo loginctl enable-linger $USER && mkdir -p ~/.config/systemd/user/default.target.wants && " +
		"sudo chown -R $USER:$USER ~/.config && " +
		"ln -sf /usr/lib/systemd/user/podman-restart.service ~/.config/systemd/user/default.target.wants/podman-restart.service && " +
		"XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload"
	exec.Command("podman", "machine", "ssh", "--", cmd).Run() //nolint:errcheck
}

// --- Auto-start at login (launchd LaunchAgent — macOS's equivalent of
// Windows's Task Scheduler entry) ---

func installLaunchAgent() error {
	podmanPath, err := exec.LookPath("podman")
	if err != nil {
		return err
	}
	home := os.Getenv("HOME")

	plist := fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>%s</string>
	<key>ProgramArguments</key>
	<array>
		<string>%s</string>
		<string>machine</string>
		<string>start</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
</dict>
</plist>
`, launchAgentLabel, podmanPath)

	agentsDir := filepath.Join(home, "Library", "LaunchAgents")
	if err := os.MkdirAll(agentsDir, 0755); err != nil {
		return err
	}
	plistPath := filepath.Join(agentsDir, launchAgentLabel+".plist")
	if err := os.WriteFile(plistPath, []byte(plist), 0644); err != nil {
		return err
	}
	exec.Command("launchctl", "unload", plistPath).Run() //nolint:errcheck
	return exec.Command("launchctl", "load", plistPath).Run()
}

// --- Applications shortcut (a minimal .app bundle wrapper — no compiled GUI,
// no cgo, no code signing: just an Info.plist and a shell script) ---

func installAppBundle(home, target string) error {
	bundleDir := filepath.Join(home, "Applications", appBundleName)
	macosDir := filepath.Join(bundleDir, "Contents", "MacOS")
	if err := os.MkdirAll(macosDir, 0755); err != nil {
		return err
	}

	infoPlist := strings.ReplaceAll(appInfoPlistTemplate, "__VERSION__", Version)
	if err := os.WriteFile(filepath.Join(bundleDir, "Contents", "Info.plist"), []byte(infoPlist), 0644); err != nil {
		return err
	}

	launcherScript := fmt.Sprintf("#!/bin/bash\nexec \"%s\" start\n", filepath.Join(target, "pie-manager"))
	launcherPath := filepath.Join(macosDir, "pie-manager-launcher")
	return os.WriteFile(launcherPath, []byte(launcherScript), 0755)
}
