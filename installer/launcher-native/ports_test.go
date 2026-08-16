package main

import (
	"net"
	"testing"
)

func TestFindAvailablePort_ReturnsStartWhenFree(t *testing.T) {
	// Use a high, unlikely-to-be-busy port as the start candidate.
	p := findAvailablePort(48120)
	if p < 48120 || p > 65534 {
		t.Errorf("expected port in [48120, 65534], got %d", p)
	}
}

func TestFindAvailablePort_SkipsBusyPort(t *testing.T) {
	ln, err := net.Listen("tcp", ":48121")
	if err != nil {
		t.Skip("port 48121 already in use — skipping")
	}
	defer ln.Close()

	p := findAvailablePort(48121)
	if p == 48121 {
		t.Error("expected a port other than 48121 (it is busy)")
	}
}

func TestSelectPorts_ReturnsDistinctFreePorts(t *testing.T) {
	p := selectPorts()
	if p.Postgres < defaultPostgresPort {
		t.Errorf("expected Postgres port >= %d, got %d", defaultPostgresPort, p.Postgres)
	}
	if p.Backend < defaultBackendPort {
		t.Errorf("expected Backend port >= %d, got %d", defaultBackendPort, p.Backend)
	}
	if p.Postgres == p.Backend {
		t.Errorf("expected distinct ports, got the same port %d for both", p.Postgres)
	}
}

func TestFindAvailablePort_FallbackWhenExhausted(t *testing.T) {
	// Bind 65534 so the loop starts there, fails, increments to 65535 which exits the loop
	// condition (port < 65535) — exercises the fallback return without exhausting the whole
	// port range. Same trick as installer/install_test.go's own findAvailablePort test.
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

func TestSelectPorts_SkipsBusyDefaultPostgresPort(t *testing.T) {
	ln, err := net.Listen("tcp", ":15432")
	if err != nil {
		t.Skip("port 15432 already in use — skipping")
	}
	defer ln.Close()

	p := selectPorts()
	if p.Postgres == 15432 {
		t.Error("expected Postgres port to skip the busy default 15432")
	}
}
