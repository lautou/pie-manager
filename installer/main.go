package main

import (
	"fmt"
	"os"
)

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
