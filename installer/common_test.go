//go:build linux

// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// --- githubLatestAssetURL ---

func TestGithubLatestAssetURL_ReturnsMatchingAsset(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(githubRelease{Assets: []githubAsset{
			{Name: "other-file.txt", BrowserDownloadURL: "http://example.com/other-file.txt"},
			{Name: "Microsoft.WSL_2.9.4.0_x64_ARM64.msixbundle", BrowserDownloadURL: "http://example.com/wsl.msixbundle"},
		}})
	}))
	defer srv.Close()

	orig := githubAPIBase
	githubAPIBase = srv.URL
	defer func() { githubAPIBase = orig }()

	url, err := githubLatestAssetURL("microsoft/WSL", "_x64_ARM64.msixbundle")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if url != "http://example.com/wsl.msixbundle" {
		t.Errorf("unexpected url: %q", url)
	}
}

func TestGithubLatestAssetURL_HTTPError(t *testing.T) {
	orig := githubAPIBase
	githubAPIBase = "://not-a-valid-url"
	defer func() { githubAPIBase = orig }()

	if _, err := githubLatestAssetURL("microsoft/WSL", ".msixbundle"); err == nil {
		t.Error("expected error for malformed API base URL")
	}
}

func TestGithubLatestAssetURL_NonOKStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	orig := githubAPIBase
	githubAPIBase = srv.URL
	defer func() { githubAPIBase = orig }()

	if _, err := githubLatestAssetURL("microsoft/WSL", ".msixbundle"); err == nil {
		t.Error("expected error for non-200 status")
	}
}

func TestGithubLatestAssetURL_InvalidJSON(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("not json"))
	}))
	defer srv.Close()

	orig := githubAPIBase
	githubAPIBase = srv.URL
	defer func() { githubAPIBase = orig }()

	if _, err := githubLatestAssetURL("microsoft/WSL", ".msixbundle"); err == nil {
		t.Error("expected error for invalid JSON body")
	}
}

func TestGithubLatestAssetURL_NoMatchingAsset(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(githubRelease{Assets: []githubAsset{
			{Name: "readme.md", BrowserDownloadURL: "http://example.com/readme.md"},
		}})
	}))
	defer srv.Close()

	orig := githubAPIBase
	githubAPIBase = srv.URL
	defer func() { githubAPIBase = orig }()

	if _, err := githubLatestAssetURL("microsoft/WSL", ".msixbundle"); err == nil {
		t.Error("expected error when no asset matches the suffix")
	}
}

// --- downloadFile ---

func TestDownloadFile_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("hello pie-manager"))
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "out.bin")
	if err := downloadFile(srv.URL, dest); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	data, err := os.ReadFile(dest)
	if err != nil {
		t.Fatalf("reading downloaded file: %v", err)
	}
	if string(data) != "hello pie-manager" {
		t.Errorf("unexpected content: %q", string(data))
	}
	if _, err := os.Stat(dest + ".part"); !os.IsNotExist(err) {
		t.Error("expected .part temp file to be renamed away")
	}
}

func TestDownloadFile_HTTPError(t *testing.T) {
	dest := filepath.Join(t.TempDir(), "out.bin")
	if err := downloadFile("://not-a-valid-url", dest); err == nil {
		t.Error("expected error for malformed URL")
	}
}

func TestDownloadFile_NonOKStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "out.bin")
	if err := downloadFile(srv.URL, dest); err == nil {
		t.Error("expected error for non-200 status")
	}
}

func TestDownloadFile_CreateError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("x"))
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "nonexistent-subdir", "out.bin")
	if err := downloadFile(srv.URL, dest); err == nil {
		t.Error("expected error when destination directory does not exist")
	}
}

func TestDownloadFile_BodyReadError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Promise more bytes than actually sent so the client detects a
		// truncated body and io.Copy returns an error.
		w.Header().Set("Content-Length", "1000")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("short"))
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "out.bin")
	if err := downloadFile(srv.URL, dest); err == nil {
		t.Error("expected error for truncated body")
	}
	if _, err := os.Stat(dest + ".part"); !os.IsNotExist(err) {
		t.Error("expected .part temp file to be cleaned up after write error")
	}
}

func TestDownloadFile_RenameError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("x"))
	}))
	defer srv.Close()

	// dest is itself an existing directory — the final rename over it must fail.
	dest := t.TempDir()
	if err := downloadFile(srv.URL, dest); err == nil {
		t.Error("expected error when dest is an existing directory")
	}
}

// --- composePostgresMajor ---

func TestComposePostgresMajor_ExtractsVersion(t *testing.T) {
	compose := []byte("services:\n  postgres:\n    image: docker.io/library/postgres:18-alpine\n")
	if got := composePostgresMajor(compose); got != "18" {
		t.Errorf("got %q, want %q", got, "18")
	}
}

func TestComposePostgresMajor_NoMatchReturnsEmpty(t *testing.T) {
	compose := []byte("services:\n  postgres:\n    image: docker.io/library/haproxy:alpine\n")
	if got := composePostgresMajor(compose); got != "" {
		t.Errorf("got %q, want empty", got)
	}
}

// --- postgresMajorMismatch ---

func TestPostgresMajorMismatch(t *testing.T) {
	cases := []struct {
		name             string
		existing, target string
		want             bool
	}{
		{"both empty", "", "", false},
		{"existing empty (fresh install)", "", "18", false},
		{"target empty (unparseable compose)", "16", "", false},
		{"equal versions", "18", "18", false},
		{"real mismatch", "16", "18", true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := postgresMajorMismatch(c.existing, c.target); got != c.want {
				t.Errorf("postgresMajorMismatch(%q, %q) = %v, want %v", c.existing, c.target, got, c.want)
			}
		})
	}
}

// --- checkPostgresUpgradeCompatibility ---

func TestCheckPostgresUpgradeCompatibility_FreshInstallIsNoop(t *testing.T) {
	if err := checkPostgresUpgradeCompatibility(""); err != nil {
		t.Errorf("expected nil for a fresh install, got %v", err)
	}
}

func TestCheckPostgresUpgradeCompatibility_SameVersionIsNoop(t *testing.T) {
	if err := checkPostgresUpgradeCompatibility(Version); err != nil {
		t.Errorf("expected nil when existing version already matches current, got %v", err)
	}
}

// --- shouldRemoveImageTag ---

func TestShouldRemoveImageTag(t *testing.T) {
	cases := []struct {
		name    string
		tag     string
		current string
		want    bool
	}{
		{"current version is kept", "1.4.7", "1.4.7", false},
		{"latest is kept", "latest", "1.4.7", false},
		{"blank tag is kept", "", "1.4.7", false},
		{"old version is removed", "1.4.6", "1.4.7", true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := shouldRemoveImageTag(c.tag, c.current); got != c.want {
				t.Errorf("shouldRemoveImageTag(%q, %q) = %v, want %v", c.tag, c.current, got, c.want)
			}
		})
	}
}

// --- selfUpdateBinary ---

func TestSelfUpdateBinary_CopiesWhenPathsDiffer(t *testing.T) {
	dir := t.TempDir()
	self := filepath.Join(dir, "self")
	dest := filepath.Join(dir, "dest")
	os.WriteFile(self, []byte("new binary"), 0755)
	os.WriteFile(dest, []byte("old binary"), 0755)

	if err := selfUpdateBinary(self, dest); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	data, _ := os.ReadFile(dest)
	if string(data) != "new binary" {
		t.Errorf("expected dest to be overwritten, got %q", string(data))
	}
	if _, err := os.Stat(dest + ".old"); !os.IsNotExist(err) {
		t.Error("expected the .old temp file to be removed after a successful copy")
	}
}

func TestSelfUpdateBinary_NoopWhenAlreadyTheSameFile(t *testing.T) {
	dir := t.TempDir()
	self := filepath.Join(dir, "self")
	os.WriteFile(self, []byte("binary"), 0755)

	if err := selfUpdateBinary(self, self); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	data, _ := os.ReadFile(self)
	if string(data) != "binary" {
		t.Errorf("expected file left untouched, got %q", string(data))
	}
}

func TestSelfUpdateBinary_RollsBackOnCopyError(t *testing.T) {
	dir := t.TempDir()
	self := filepath.Join(dir, "missing-self") // copyFile fails: source doesn't exist
	dest := filepath.Join(dir, "dest")
	os.WriteFile(dest, []byte("old binary"), 0755)

	if err := selfUpdateBinary(self, dest); err == nil {
		t.Fatal("expected error when the source binary is missing")
	}
	data, _ := os.ReadFile(dest)
	if string(data) != "old binary" {
		t.Errorf("expected dest restored to its original content after rollback, got %q", string(data))
	}
}

// --- writeInstallConfig ---

func withTestAssets(t *testing.T, compose, haproxy []byte) {
	t.Helper()
	origCompose, origHaproxy := composeProd, haproxyCfg
	composeProd, haproxyCfg = compose, haproxy
	t.Cleanup(func() { composeProd, haproxyCfg = origCompose, origHaproxy })
}

func TestWriteInstallConfig_WritesAllFiles(t *testing.T) {
	withTestAssets(t, []byte("services:\n  postgres:\n    image: docker.io/library/postgres:18-alpine\n"), []byte("# haproxy config\n"))

	dir := t.TempDir()
	target := filepath.Join(dir, "install-target") // also exercises the MkdirAll branch
	if err := writeInstallConfig(target, "1.2.3"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	compose, _ := os.ReadFile(filepath.Join(target, "compose-prod.yaml"))
	if string(compose) != string(composeProd) {
		t.Error("compose-prod.yaml not written correctly")
	}
	haproxy, _ := os.ReadFile(filepath.Join(target, "haproxy.cfg"))
	if string(haproxy) != string(haproxyCfg) {
		t.Error("haproxy.cfg not written correctly")
	}
	version, _ := os.ReadFile(filepath.Join(target, "VERSION"))
	if strings.TrimSpace(string(version)) != Version {
		t.Errorf("VERSION not written correctly, got %q", string(version))
	}
	env, _ := os.ReadFile(filepath.Join(target, ".env"))
	if !strings.Contains(string(env), "APP_VERSION=1.2.3") {
		t.Errorf("expected .env to contain APP_VERSION=1.2.3, got %q", string(env))
	}
	if !strings.Contains(string(env), "APP_PORT=") {
		t.Error("expected .env to contain an APP_PORT")
	}
}

func TestWriteInstallConfig_PicksFallbackPortWhenDefaultIsBusy(t *testing.T) {
	withTestAssets(t, []byte("compose"), []byte("haproxy"))

	ln, err := net.Listen("tcp", fmt.Sprintf(":%d", defaultPort))
	if err != nil {
		t.Skip("default port already in use — skipping")
	}
	defer ln.Close()

	dir := t.TempDir()
	if err := writeInstallConfig(dir, "1.2.3"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	env, _ := os.ReadFile(filepath.Join(dir, ".env"))
	if strings.Contains(string(env), fmt.Sprintf("APP_PORT=%d", defaultPort)) {
		t.Errorf("expected a fallback port, got default port in .env: %q", string(env))
	}
}

func TestWriteInstallConfig_MkdirError(t *testing.T) {
	dir := t.TempDir()
	blocker := filepath.Join(dir, "blocker")
	os.WriteFile(blocker, []byte("x"), 0644)
	target := filepath.Join(blocker, "subdir") // MkdirAll under a file, not a dir -> error

	if err := writeInstallConfig(target, "1.2.3"); err == nil {
		t.Error("expected error when target's parent path is a file")
	}
}

func TestWriteInstallConfig_ComposeWriteError(t *testing.T) {
	withTestAssets(t, []byte("compose"), []byte("haproxy"))
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, "compose-prod.yaml"), 0755)

	if err := writeInstallConfig(dir, "1.2.3"); err == nil {
		t.Error("expected error when compose-prod.yaml path is a directory")
	}
}

func TestWriteInstallConfig_VersionWriteError(t *testing.T) {
	withTestAssets(t, []byte("compose"), []byte("haproxy"))
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, "VERSION"), 0755)

	if err := writeInstallConfig(dir, "1.2.3"); err == nil {
		t.Error("expected error when VERSION path is a directory")
	}
}

func TestWriteInstallConfig_EnvWriteError(t *testing.T) {
	withTestAssets(t, []byte("compose"), []byte("haproxy"))
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, ".env"), 0755)

	err := writeInstallConfig(dir, "1.2.3")
	if err == nil || !strings.Contains(err.Error(), "writing .env") {
		t.Errorf("expected a wrapped .env write error, got %v", err)
	}
}

func TestWriteInstallConfig_HaproxyWriteError(t *testing.T) {
	withTestAssets(t, []byte("compose"), []byte("haproxy"))
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, "haproxy.cfg"), 0755)

	err := writeInstallConfig(dir, "1.2.3")
	if err == nil || !strings.Contains(err.Error(), "writing haproxy.cfg") {
		t.Errorf("expected a wrapped haproxy.cfg write error, got %v", err)
	}
}
