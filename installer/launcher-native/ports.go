// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"fmt"
	"net"
)

// defaultPostgresPort/defaultBackendPort are starting candidates, not guarantees — real ports
// are always resolved via findAvailablePort. Hardcoding a fixed port (the #76 poc always used
// 5432/8123 unconditionally) risks conflicting with an already-running Docker Desktop, WSL2, or
// another local Postgres instance in real use. 15432 (not 5432) is used as Postgres's starting
// candidate specifically to avoid colliding with a genuinely running system-wide Postgres a
// user might already have, rather than immediately bumping past it every time.
const (
	defaultPostgresPort = 15432
	defaultBackendPort  = 14943 // matches installer/common.go's defaultPort for the Podman-based product
)

// findAvailablePort returns the first free TCP port starting from start. Duplicated from
// installer/common.go (a separate Go module, not importable across module boundaries) rather
// than extracting a shared internal package — this is 8 lines of trivial, already-tested logic,
// not worth the cross-module coupling risk to the existing shipped installer.
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

// ports bundles the two dynamically-resolved ports this app needs at runtime.
type ports struct {
	Postgres int
	Backend  int
}

// selectPorts resolves both ports fresh on every launch — never persisted, since a port that
// was free last time may not be free now (another app claimed it, or a stale process from a
// previous crashed session is still bound to it — see crash_recovery.go for that check).
func selectPorts() ports {
	return ports{
		Postgres: findAvailablePort(defaultPostgresPort),
		Backend:  findAvailablePort(defaultBackendPort),
	}
}
