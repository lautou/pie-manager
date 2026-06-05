package main

import (
	"fmt"
	"net"
	"os"
	"path/filepath"
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
