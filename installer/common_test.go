//go:build linux

package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
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
