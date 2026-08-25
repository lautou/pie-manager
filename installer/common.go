// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const defaultPort = 14943

// maxStartupWaitSeconds bounds how long performStart polls the app's health endpoint after
// starting services before giving up and printing the URL anyway (the app usually keeps
// starting in the background regardless).
const maxStartupWaitSeconds = 90

// Version is injected at build time via -ldflags "-X main.Version=x.y.z"
var Version = "dev"

func main() {
	cmd := "install"
	if len(os.Args) > 1 {
		cmd = os.Args[1]
	}

	switch cmd {
	case "start":
		runStart()
	case "version", "--version", "-v":
		fmt.Println(Version)
	case "help", "--help", "-h":
		printUsage()
	default:
		runInstall()
	}
}

func printUsage() {
	fmt.Printf(`PIE Manager %s — Installer / Launcher

Usage:
  pie-manager [install]  Install or update the application (default)
  pie-manager start      Start services and open the browser
  pie-manager version    Print the version
`, Version)
}

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

// readAppPort reads APP_PORT from the install dir's .env file, falling back to defaultPort.
func readAppPort(target string) int {
	data, err := os.ReadFile(filepath.Join(target, ".env"))
	if err != nil {
		return defaultPort
	}
	for _, line := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(line, "APP_PORT=") {
			val := strings.TrimSpace(strings.TrimPrefix(line, "APP_PORT="))
			if p, err := strconv.Atoi(val); err == nil && p > 0 {
				return p
			}
		}
	}
	return defaultPort
}

// updateEnvPort rewrites APP_PORT in the install dir's .env file.
func updateEnvPort(target string, port int) {
	path := filepath.Join(target, ".env")
	data, _ := os.ReadFile(path)
	re := regexp.MustCompile(`(?m)^APP_PORT=.*$`)
	updated := re.ReplaceAllString(string(data), fmt.Sprintf("APP_PORT=%d", port))
	if !strings.Contains(updated, "APP_PORT=") {
		updated += fmt.Sprintf("\nAPP_PORT=%d\n", port)
	}
	os.WriteFile(path, []byte(updated), 0644) //nolint:errcheck
}

// readInstalledVersion reads the VERSION file from a previous install, if any.
func readInstalledVersion(target string) string {
	data, err := os.ReadFile(filepath.Join(target, "VERSION"))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

// detectComposeCmd prefers a standalone podman-compose binary, falling back
// to the podman compose subcommand.
func detectComposeCmd() string {
	if _, err := exec.LookPath("podman-compose"); err == nil {
		return "podman-compose"
	}
	return "podman compose"
}

// podmanImageExists reports whether image is already present locally.
func podmanImageExists(image string) bool {
	return exec.Command("podman", "image", "exists", image).Run() == nil
}

// forceRecreate brings the compose stack down then up. `up`'s stdout is surfaced (not
// discarded) — a real hang was once invisible in CI logs specifically because this was
// io.Discard, hiding every podman-compose orchestration message after the last image pull.
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
	up.Stdout = os.Stdout
	up.Stderr = os.Stderr
	up.Run() //nolint:errcheck
}

// copyFile copies src to dst, creating/truncating dst with the given permissions.
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

// githubAPIBase is the GitHub API base URL — overridable in tests to point
// at an httptest.Server instead of the real GitHub API.
var githubAPIBase = "https://api.github.com"

type githubAsset struct {
	Name               string `json:"name"`
	BrowserDownloadURL string `json:"browser_download_url"`
}

type githubRelease struct {
	Assets []githubAsset `json:"assets"`
}

// githubLatestAssetURL returns the download URL of the first asset in repo's
// latest GitHub release whose name ends with suffix. Used to resolve
// official vendor-published packages (e.g. Podman's macOS .pkg) without
// hardcoding a version-specific filename that changes on every release.
func githubLatestAssetURL(repo, suffix string) (string, error) {
	url := fmt.Sprintf("%s/repos/%s/releases/latest", githubAPIBase, repo)
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return "", fmt.Errorf("building request for %s: %w", repo, err)
	}
	// GitHub's API rate-limits unauthenticated requests to 60/hour per IP —
	// shared GitHub Actions runner IPs can already be near that limit
	// (confirmed live: a real 403 testing this installer in CI). A real end
	// user's own installer run never has this env var set, so this is a
	// no-op outside CI; inside CI it lifts the limit to 5000/hour.
	if token := os.Getenv("GITHUB_TOKEN"); token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	} else if token := os.Getenv("GH_TOKEN"); token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("fetching latest release for %s: %w", repo, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("unexpected status %d fetching latest release for %s", resp.StatusCode, repo)
	}
	var rel githubRelease
	if err := json.NewDecoder(resp.Body).Decode(&rel); err != nil {
		return "", fmt.Errorf("decoding release JSON for %s: %w", repo, err)
	}
	for _, a := range rel.Assets {
		if strings.HasSuffix(a.Name, suffix) {
			return a.BrowserDownloadURL, nil
		}
	}
	return "", fmt.Errorf("no asset ending in %q found in latest release of %s", suffix, repo)
}

// downloadFile streams url to dest. It writes to a temporary "dest.part"
// file first and renames it into place on success, so a failed or
// interrupted download never leaves a corrupt file at dest.
func downloadFile(url, dest string) error {
	resp, err := http.Get(url)
	if err != nil {
		return fmt.Errorf("downloading %s: %w", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("unexpected status %d downloading %s", resp.StatusCode, url)
	}

	tmp := dest + ".part"
	f, err := os.Create(tmp)
	if err != nil {
		return fmt.Errorf("creating %s: %w", tmp, err)
	}
	if _, err := io.Copy(f, resp.Body); err != nil {
		f.Close()
		os.Remove(tmp)
		return fmt.Errorf("writing %s: %w", tmp, err)
	}
	f.Close()
	if err := os.Rename(tmp, dest); err != nil {
		return fmt.Errorf("renaming %s to %s: %w", tmp, dest, err)
	}
	return nil
}

// pgDataVolumeName finds the app's Postgres data volume by suffix rather than
// reconstructing podman-compose's project-name-derivation algorithm from the install
// directory's basename — that algorithm differs subtly between podman-compose and podman's
// own native `compose` subcommand, and this project has never needed to reproduce it until
// now (see issue #58). In practice exactly one local volume ends in "_postgres_data" per
// install. Returns "" if no such volume exists yet (fresh install).
func pgDataVolumeName() string {
	out, err := exec.Command("podman", "volume", "ls", "--format", "{{.Name}}").Output()
	if err != nil {
		return ""
	}
	for _, name := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if strings.HasSuffix(name, "_postgres_data") {
			return name
		}
	}
	return ""
}

// pgVersionMajor reads the PG_VERSION file from a named Postgres data volume via a
// throwaway alpine reader — it never starts postgres itself, so this is safe to call
// before deciding whether starting a newer major version against the volume is even safe
// (issue #58). Every Postgres data directory contains this plain-text major-version marker
// regardless of major version. Returns "" if the volume can't be read for any reason;
// callers treat that as "nothing to compare against," never as a hard error.
func pgVersionMajor(volumeName string) string {
	out, err := exec.Command("podman", "run", "--rm",
		"-v", volumeName+":/mnt:ro",
		"docker.io/library/alpine", "cat", "/mnt/PG_VERSION").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// composePostgresMajor extracts the target Postgres major version from an embedded
// compose-prod.yaml's image tag (e.g. "postgres:18-alpine" -> "18"), parsed directly rather
// than hardcoded as a separate constant so it can never drift from what's actually
// embedded.
func composePostgresMajor(compose []byte) string {
	m := regexp.MustCompile(`docker\.io/library/postgres:(\d+)-alpine`).FindSubmatch(compose)
	if m == nil {
		return ""
	}
	return string(m[1])
}

// postgresMajorMismatch reports whether an existing data volume's Postgres major version
// differs from the version a new compose file is about to start. PostgreSQL major versions
// are not binary-compatible — starting a newer major against an older on-disk format
// crashes the container outright rather than failing gracefully, so this must be checked
// BEFORE any image pull or forceRecreate, not discovered from a crash loop afterward (issue
// #58). "" on either side (nothing detected, e.g. a fresh install with no existing volume)
// never counts as a mismatch.
func postgresMajorMismatch(existing, target string) bool {
	return existing != "" && target != "" && existing != target
}

// performInstall runs the platform-independent core of the install flow shared by Linux's
// and macOS's own runInstall: resolve the install directory, guard against a PostgreSQL
// major-version mismatch, pull container images, write config files, self-copy the binary,
// start services, and clean up old image versions. `composeProd`/`haproxyCfg` are resolved
// from whichever platform file's own //go:embed declares them (install.go/install_darwin.go),
// mutually exclusive per build tag. The two real platform differences are injected as
// callbacks: onPodmanMachineReady runs right after the version-mismatch guard (a no-op on
// Linux; initializes/starts Podman Machine on macOS), and onDesktopIntegration owns every
// platform-specific post-install step — including its own progress printing, since Linux and
// macOS don't even share the same number of labeled steps here (macOS has an extra
// "Configuring container auto-restart..." step Linux has no equivalent of).
func performInstall(
	home, target string,
	onPodmanMachineReady func() error,
	onDesktopIntegration func(home, target string),
	launchHint string,
) {
	fmt.Printf("Install directory: %s\n", target)

	existingVersion := readInstalledVersion(target)
	if existingVersion != "" && existingVersion != Version {
		if volumeName := pgDataVolumeName(); volumeName != "" {
			existingPGMajor := pgVersionMajor(volumeName)
			targetPGMajor := composePostgresMajor(composeProd)
			if postgresMajorMismatch(existingPGMajor, targetPGMajor) {
				fmt.Printf("\n✗ PostgreSQL major version mismatch: your data is on PostgreSQL %s, "+
					"but PIE Manager %s requires PostgreSQL %s.\n", existingPGMajor, Version, targetPGMajor)
				fmt.Println("  A direct upgrade is not possible — PostgreSQL major versions are not")
				fmt.Println("  binary-compatible, and the new database container would simply refuse")
				fmt.Println("  to start against your existing data. Nothing has been changed.")
				fmt.Println("\n  Manual migration required:")
				fmt.Printf("    1. If PIE Manager %s is still running, open it now and go to\n", existingVersion)
				fmt.Println("       Administration système → Télécharger une sauvegarde. Keep the file safe.")
				fmt.Println("    2. Stop PIE Manager, then remove the old database:")
				fmt.Printf("         podman volume rm %s\n", volumeName)
				fmt.Printf("    3. Re-run this installer — it will start fresh on PostgreSQL %s.\n", targetPGMajor)
				fmt.Println("    4. Once running, go to Administration système → Restaurer une sauvegarde")
				fmt.Println("       and select the file you downloaded in step 1.")
				os.Exit(1)
			}
		}
		fmt.Printf("Updating: %s → %s\n\n", existingVersion, Version)
		fmt.Println("⚠  Backup recommended before upgrading.")
		fmt.Println("   Open PIE Manager → Administration système → Télécharger une sauvegarde")
		fmt.Print("   Press Enter when done (or Ctrl+C to cancel)...")
		fmt.Scanln()
	}

	if err := onPodmanMachineReady(); err != nil {
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
		"docker.io/library/postgres:18-alpine",
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

	onDesktopIntegration(home, target)

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
	fmt.Println("  " + launchHint)
}

// performStart runs the platform-independent core of start.go's/start_darwin.go's own
// runStartWithCompose: if the app is already responding, hand off to onAlreadyRunning and
// return; otherwise resolve a free port, pull images if needed, (re)start services via
// forceRecreate, and poll the health endpoint until ready or maxStartupWaitSeconds elapses.
// onPodmanMachineReady mirrors performInstall's own hook (no-op on Linux; ensures Podman
// Machine is running on macOS). notify's signature is shared across both platforms (macOS
// ignores `urgency`, which has no equivalent there) specifically so this core can call it
// uniformly.
func performStart(
	composeCmd, target string,
	onPodmanMachineReady func() error,
	onAlreadyRunning func(url string),
) {
	composePath := filepath.Join(target, "compose-prod.yaml")
	port := readAppPort(target)
	url := fmt.Sprintf("http://localhost:%d", port)

	if resp, err := http.Get(url); err == nil { //nolint:noctx
		resp.Body.Close()
		onAlreadyRunning(url)
		return
	}

	if ln, err := net.Listen("tcp", fmt.Sprintf(":%d", port)); err != nil {
		newPort := findAvailablePort(port + 1)
		fmt.Printf("Port %d is now in use, switching to %d…\n", port, newPort)
		updateEnvPort(target, newPort)
		port = newPort
		url = fmt.Sprintf("http://localhost:%d", port)
	} else {
		ln.Close()
	}

	notify("PIE Manager", "Starting…", "low")

	if err := onPodmanMachineReady(); err != nil {
		fmt.Printf("ERROR: %v\n", err)
		os.Exit(1)
	}

	if !podmanImageExists("quay.io/ltourreau/pie-manager-backend:" + Version) {
		notify("PIE Manager", "Downloading images…", "low")
		for _, img := range []string{
			"quay.io/ltourreau/pie-manager-backend:" + Version,
			"quay.io/ltourreau/pie-manager-frontend:" + Version,
		} {
			fmt.Printf("  Pulling %s…\n", img)
			pull := exec.Command("podman", "pull", img)
			pull.Stdout = os.Stdout
			pull.Stderr = os.Stderr
			pull.Run() //nolint:errcheck
		}
	}

	go openBrowser(url)

	notify("PIE Manager", "Starting services…", "low")
	forceRecreate(composeCmd, composePath)

	fmt.Println("Waiting for PIE Manager to be ready…")
	statusMessages := map[int]string{
		5:  "  → Containers started, waiting for database…",
		15: "  → Database ready, starting backend…",
		30: "  → Backend starting (running migrations)…",
		50: "  → Still starting — first launch may take up to 90 s…",
		70: "  → Almost there…",
	}
	for i := 0; i < maxStartupWaitSeconds; i++ {
		resp, err := http.Get(url) //nolint:noctx
		if err == nil {
			resp.Body.Close()
			fmt.Printf("  ✓ Ready in %ds\n", i)
			break
		}
		if msg, ok := statusMessages[i]; ok {
			fmt.Println(msg)
			notify("PIE Manager", msg[5:], "low")
		}
		time.Sleep(time.Second)
	}

	notify("PIE Manager", "Ready!", "normal")
	fmt.Printf("PIE Manager available at %s\n", url)
}
