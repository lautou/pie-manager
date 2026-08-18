package main

import (
	"archive/zip"
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
)

const defaultPort = 14943

// Version is injected at build time via -ldflags "-X main.Version=x.y.z"
var Version = "dev"

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
// official Microsoft-published packages (WSL, winget) without hardcoding a
// version-specific filename that changes on every release.
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

// extractZipEntryBySuffix opens zipPath (any zip-format file, including a
// NuGet .nupkg, which is a zip) and copies the first entry whose path ends
// with suffix to dest.
func extractZipEntryBySuffix(zipPath, suffix, dest string) error {
	r, err := zip.OpenReader(zipPath)
	if err != nil {
		return fmt.Errorf("opening zip %s: %w", zipPath, err)
	}
	defer r.Close()

	for _, entry := range r.File {
		if !strings.HasSuffix(filepath.ToSlash(entry.Name), suffix) {
			continue
		}
		rc, err := entry.Open()
		if err != nil {
			return fmt.Errorf("opening zip entry %s: %w", entry.Name, err)
		}
		defer rc.Close()

		out, err := os.Create(dest)
		if err != nil {
			return fmt.Errorf("creating %s: %w", dest, err)
		}
		defer out.Close()

		if _, err := io.Copy(out, rc); err != nil {
			return fmt.Errorf("extracting %s: %w", entry.Name, err)
		}
		return nil
	}
	return fmt.Errorf("no entry ending in %q found in %s", suffix, zipPath)
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

// isAppxAlreadyNewerError reports whether an Add-AppxPackage failure message
// indicates the package is already satisfied by an equal-or-newer version
// already installed (HRESULT 0x80073D06) — a benign outcome, not a real
// failure. Some Windows 11 builds already ship a newer in-box copy of a
// framework package (confirmed live: Microsoft.UI.Xaml.2.8 pre-installed at
// 8.2511.26001.0, newer than the 8.2310.30001.0 this installer pins via
// NuGet) and AppX framework dependency resolution only requires "at least
// this version" — a dependent package (winget) installs and runs fine
// regardless of this specific step reporting failure. The HRESULT is
// locale-independent; the surrounding message text is not, so match on it.
func isAppxAlreadyNewerError(errOutput string) bool {
	return strings.Contains(errOutput, "0x80073D06")
}
