package main

import (
	"fmt"
	"net"
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
