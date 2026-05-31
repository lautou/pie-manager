package main

import (
	"net"
	"os"
	"path/filepath"
	"testing"
)

// --- findAvailablePort ---

func TestFindAvailablePort_ReturnsDefault(t *testing.T) {
	p := findAvailablePort(14943)
	if p < 14943 || p > 65534 {
		t.Errorf("expected port in [14943, 65534], got %d", p)
	}
}

func TestFindAvailablePort_SkipsBusyPort(t *testing.T) {
	// Occupy port 14943 so the function must pick the next one
	ln, err := net.Listen("tcp", ":14943")
	if err != nil {
		t.Skip("port 14943 already in use — skipping")
	}
	defer ln.Close()

	p := findAvailablePort(14943)
	if p == 14943 {
		t.Error("expected a port other than 14943 (it is busy)")
	}
	if p < 14944 {
		t.Errorf("expected port >= 14944, got %d", p)
	}
}

// --- readInstalledVersion ---

func TestReadInstalledVersion_Missing(t *testing.T) {
	dir := t.TempDir()
	if v := readInstalledVersion(dir); v != "" {
		t.Errorf("expected empty string for missing VERSION, got %q", v)
	}
}

func TestReadInstalledVersion_Present(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "VERSION"), []byte("1.0.0\n"), 0644)
	if v := readInstalledVersion(dir); v != "1.0.0" {
		t.Errorf("expected 1.0.0, got %q", v)
	}
}

func TestReadInstalledVersion_TrimsWhitespace(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "VERSION"), []byte("  1.2.3  \n"), 0644)
	if v := readInstalledVersion(dir); v != "1.2.3" {
		t.Errorf("expected trimmed version, got %q", v)
	}
}

// --- readAppPort / updateEnvPort ---

func TestReadAppPort_DefaultWhenMissing(t *testing.T) {
	dir := t.TempDir()
	if p := readAppPort(dir); p != defaultPort {
		t.Errorf("expected defaultPort %d, got %d", defaultPort, p)
	}
}

func TestReadAppPort_ParsesFromEnv(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, ".env"), []byte("APP_VERSION=1.0.0\nAPP_PORT=15000\n"), 0644)
	if p := readAppPort(dir); p != 15000 {
		t.Errorf("expected 15000, got %d", p)
	}
}

func TestReadAppPort_DefaultOnInvalidValue(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, ".env"), []byte("APP_PORT=notanumber\n"), 0644)
	if p := readAppPort(dir); p != defaultPort {
		t.Errorf("expected defaultPort on invalid value, got %d", p)
	}
}

func TestUpdateEnvPort_WritesNewPort(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, ".env"), []byte("APP_VERSION=1.0.0\nAPP_PORT=14943\n"), 0644)
	updateEnvPort(dir, 15001)
	if p := readAppPort(dir); p != 15001 {
		t.Errorf("expected 15001 after update, got %d", p)
	}
}

func TestUpdateEnvPort_AddsWhenMissing(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, ".env"), []byte("APP_VERSION=1.0.0\n"), 0644)
	updateEnvPort(dir, 15002)
	if p := readAppPort(dir); p != 15002 {
		t.Errorf("expected 15002 after adding APP_PORT, got %d", p)
	}
}

func TestUpdateEnvPort_PreservesOtherVars(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, ".env"), []byte("APP_VERSION=1.0.0\nAPP_PORT=14943\n"), 0644)
	updateEnvPort(dir, 15003)
	data, _ := os.ReadFile(filepath.Join(dir, ".env"))
	content := string(data)
	if !contains(content, "APP_VERSION=1.0.0") {
		t.Error("APP_VERSION was lost after updateEnvPort")
	}
}

// --- detectComposeCmd ---

func TestDetectComposeCmd_ReturnsFallback(t *testing.T) {
	cmd := detectComposeCmd()
	if cmd != "podman-compose" && cmd != "podman compose" {
		t.Errorf("unexpected compose command %q", cmd)
	}
}

// helper
func contains(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub ||
		len(s) > 0 && (s[:len(sub)] == sub ||
			contains(s[1:], sub)))
}

// --- copyFile ---

func TestCopyFile_CopiesContent(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src.txt")
	dst := filepath.Join(dir, "dst.txt")
	os.WriteFile(src, []byte("hello pie-manager"), 0644)

	if err := copyFile(src, dst, 0644); err != nil {
		t.Fatalf("copyFile failed: %v", err)
	}
	data, _ := os.ReadFile(dst)
	if string(data) != "hello pie-manager" {
		t.Errorf("unexpected content: %q", string(data))
	}
}

func TestCopyFile_SetsPerm(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src")
	dst := filepath.Join(dir, "dst")
	os.WriteFile(src, []byte("x"), 0644)

	if err := copyFile(src, dst, 0755); err != nil {
		t.Fatalf("copyFile failed: %v", err)
	}
	info, _ := os.Stat(dst)
	if info.Mode().Perm() != 0755 {
		t.Errorf("expected 0755, got %v", info.Mode().Perm())
	}
}

func TestCopyFile_ErrMissingSrc(t *testing.T) {
	dir := t.TempDir()
	err := copyFile(filepath.Join(dir, "missing"), filepath.Join(dir, "dst"), 0644)
	if err == nil {
		t.Error("expected error for missing source")
	}
}

// --- detectComposeCmd ---

func TestDetectComposeCmd_ValidCommand(t *testing.T) {
	cmd := detectComposeCmd()
	if cmd != "podman-compose" && cmd != "podman compose" {
		t.Errorf("unexpected compose command %q — must be podman-compose or podman compose", cmd)
	}
}

func TestFindAvailablePort_FallbackWhenBusy(t *testing.T) {
	// Bind 65534 so the loop starts there, fails, increments to 65535 which
	// exits the loop condition (port < 65535), exercising the fallback return.
	ln, err := net.Listen("tcp", ":65534")
	if err != nil {
		t.Skip("port 65534 already in use — skipping fallback test")
	}
	defer ln.Close()
	p := findAvailablePort(65534)
	if p != 65534 {
		t.Errorf("expected fallback to start=65534, got %d", p)
	}
}

func TestDetectComposeCmd_FindsPodmanCompose(t *testing.T) {
	// Create a fake podman-compose in a temp dir and prepend it to PATH
	dir := t.TempDir()
	fake := filepath.Join(dir, "podman-compose")
	os.WriteFile(fake, []byte("#!/bin/sh\n"), 0755)

	origPath := os.Getenv("PATH")
	os.Setenv("PATH", dir+":"+origPath)
	defer os.Setenv("PATH", origPath)

	if cmd := detectComposeCmd(); cmd != "podman-compose" {
		t.Errorf("expected podman-compose, got %q", cmd)
	}
}

func TestCopyFile_ErrDstIsDir(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src")
	os.WriteFile(src, []byte("x"), 0644)
	// dst points to a directory — os.OpenFile for write fails with EISDIR
	err := copyFile(src, dir, 0644)
	if err == nil {
		t.Error("expected error when dst is a directory")
	}
}
