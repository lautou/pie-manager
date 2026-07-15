//go:build linux

package main

import (
	"archive/zip"
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

// --- extractZipEntryBySuffix ---

func TestExtractZipEntryBySuffix_Success(t *testing.T) {
	dir := t.TempDir()
	zipPath := filepath.Join(dir, "pkg.zip")
	writeTestZip(t, zipPath, map[string]string{
		"tools/AppX/x64/Release/Microsoft.UI.Xaml.2.8.appx": "appx-content",
		"other/file.txt": "irrelevant",
	})

	dest := filepath.Join(dir, "out.appx")
	if err := extractZipEntryBySuffix(zipPath, "Microsoft.UI.Xaml.2.8.appx", dest); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	data, err := os.ReadFile(dest)
	if err != nil {
		t.Fatalf("reading extracted file: %v", err)
	}
	if string(data) != "appx-content" {
		t.Errorf("unexpected content: %q", string(data))
	}
}

func TestExtractZipEntryBySuffix_BadZip(t *testing.T) {
	dir := t.TempDir()
	notZip := filepath.Join(dir, "notzip.bin")
	os.WriteFile(notZip, []byte("not a zip file"), 0644)

	err := extractZipEntryBySuffix(notZip, ".appx", filepath.Join(dir, "out.appx"))
	if err == nil {
		t.Error("expected error opening a non-zip file")
	}
}

func TestExtractZipEntryBySuffix_EntryNotFound(t *testing.T) {
	dir := t.TempDir()
	zipPath := filepath.Join(dir, "pkg.zip")
	writeTestZip(t, zipPath, map[string]string{"readme.txt": "hello"})

	err := extractZipEntryBySuffix(zipPath, ".appx", filepath.Join(dir, "out.appx"))
	if err == nil {
		t.Error("expected error when no entry matches the suffix")
	}
}

func TestExtractZipEntryBySuffix_EntryOpenError(t *testing.T) {
	dir := t.TempDir()
	zipPath := filepath.Join(dir, "pkg.zip")
	// Method 99 is not a compression method Go's zip package supports —
	// entry.Open() itself rejects it before any data is read.
	writeRawZipEntry(t, zipPath, "bad.appx", 99, 0, []byte("irrelevant"))

	err := extractZipEntryBySuffix(zipPath, ".appx", filepath.Join(dir, "out.appx"))
	if err == nil {
		t.Error("expected error opening an entry with an unsupported compression method")
	}
}

func TestExtractZipEntryBySuffix_CreateDestError(t *testing.T) {
	dir := t.TempDir()
	zipPath := filepath.Join(dir, "pkg.zip")
	writeTestZip(t, zipPath, map[string]string{"file.appx": "content"})

	dest := filepath.Join(dir, "nonexistent-subdir", "out.appx")
	err := extractZipEntryBySuffix(zipPath, ".appx", dest)
	if err == nil {
		t.Error("expected error when destination directory does not exist")
	}
}

func TestExtractZipEntryBySuffix_CopyError(t *testing.T) {
	dir := t.TempDir()
	zipPath := filepath.Join(dir, "pkg.zip")
	// Deflate (method 8) is a supported/registered method, so entry.Open()
	// succeeds — but these raw bytes aren't a valid deflate stream, so
	// decompressing them during io.Copy fails, unlike an Open()-time error.
	writeRawZipEntry(t, zipPath, "bad.appx", 8, 0, []byte("not a valid deflate stream at all"))

	err := extractZipEntryBySuffix(zipPath, ".appx", filepath.Join(dir, "out.appx"))
	if err == nil {
		t.Error("expected error copying an entry with invalid compressed data")
	}
}

// --- isAppxAlreadyNewerError ---

func TestIsAppxAlreadyNewerError_MatchesHRESULT(t *testing.T) {
	msg := `exit status 1 (output: Add-AppxPackage : Deployment failed with HRESULT: 0x80073D06, ` +
		`Impossible d'installer ce package, car une version ultérieure est déjà installée.)`
	if !isAppxAlreadyNewerError(msg) {
		t.Error("expected true for a message containing HRESULT 0x80073D06")
	}
}

func TestIsAppxAlreadyNewerError_UnrelatedError(t *testing.T) {
	msg := "exit status 1 (output: Add-AppxPackage : Deployment failed with HRESULT: 0x80073CF9)"
	if isAppxAlreadyNewerError(msg) {
		t.Error("expected false for an unrelated HRESULT")
	}
}

func TestIsAppxAlreadyNewerError_Empty(t *testing.T) {
	if isAppxAlreadyNewerError("") {
		t.Error("expected false for an empty message")
	}
}

// writeRawZipEntry creates a zip file with a single entry whose header lies
// about its compression method and/or CRC32 relative to the raw bytes
// written — used to deterministically trigger entry.Open()/Read() failures
// that a well-formed zip.Writer.Create() call cannot produce.
func writeRawZipEntry(t *testing.T, path, name string, method uint16, crc32 uint32, raw []byte) {
	t.Helper()
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("creating test zip: %v", err)
	}
	defer f.Close()

	zw := zip.NewWriter(f)
	fh := &zip.FileHeader{
		Name:               name,
		Method:             method,
		CRC32:              crc32,
		CompressedSize64:   uint64(len(raw)),
		UncompressedSize64: uint64(len(raw)),
	}
	w, err := zw.CreateRaw(fh)
	if err != nil {
		t.Fatalf("creating raw zip entry: %v", err)
	}
	if _, err := w.Write(raw); err != nil {
		t.Fatalf("writing raw zip entry: %v", err)
	}
	if err := zw.Close(); err != nil {
		t.Fatalf("closing zip writer: %v", err)
	}
}

// writeTestZip creates a zip file at path containing the given entries.
func writeTestZip(t *testing.T, path string, files map[string]string) {
	t.Helper()
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("creating test zip: %v", err)
	}
	defer f.Close()

	zw := zip.NewWriter(f)
	for name, content := range files {
		w, err := zw.Create(name)
		if err != nil {
			t.Fatalf("creating zip entry %s: %v", name, err)
		}
		if _, err := w.Write([]byte(content)); err != nil {
			t.Fatalf("writing zip entry %s: %v", name, err)
		}
	}
	if err := zw.Close(); err != nil {
		t.Fatalf("closing zip writer: %v", err)
	}
}
