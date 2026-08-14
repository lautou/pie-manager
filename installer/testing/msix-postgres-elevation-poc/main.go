// Command poc is a throwaway diagnostic build for issue #76 — see ../README.md. It never
// ships in the real product. Packaged as a full-trust MSIX and launched via its AUMID, it has
// no console attached, so all it does is resolve its own package paths, write out the worker
// PowerShell script (embedded below) to a temp file, run it with those paths as parameters, and
// exit. PowerShell is used for the actual test logic instead of raw Win32 syscalls from Go
// specifically so the measurement ([Security.Principal.WindowsPrincipal]::IsInRole(Administrator))
// is a well-known, widely used one-liner — not a hand-rolled token/SID syscall wrapper with no
// local Windows dev loop to iterate against. The worker is invoked via -File (a temp .ps1), not
// -Command with an inline string, so package paths containing spaces (e.g. under
// "C:\Program Files\WindowsApps\...") never need manual command-line quoting.
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

func writeResult(resultPath, body string) {
	_ = os.WriteFile(resultPath, []byte(body), 0o644)
}

func main() {
	tempDir := os.Getenv("TEMP")
	resultPath := filepath.Join(tempDir, "msix-postgres-elevation-poc-result.txt")

	exePath, err := os.Executable()
	if err != nil {
		writeResult(resultPath, fmt.Sprintf("FAILURE: os.Executable() error: %v", err))
		return
	}
	pkgRoot := filepath.Dir(exePath)

	localAppData := os.Getenv("LOCALAPPDATA")
	matches, _ := filepath.Glob(filepath.Join(localAppData, "Packages", "PieManagerMsixPostgresElevationPoc_*"))
	if len(matches) == 0 {
		writeResult(resultPath, "FAILURE: could not resolve this package's LocalState directory "+
			"(no Packages\\PieManagerMsixPostgresElevationPoc_* match under %LOCALAPPDATA%)")
		return
	}
	pgData := filepath.Join(matches[0], "LocalState", "pgdata")

	scriptPath := filepath.Join(tempDir, "msix-poc-worker.ps1")
	if err := os.WriteFile(scriptPath, []byte(workerScript), 0o644); err != nil {
		writeResult(resultPath, fmt.Sprintf("FAILURE: could not write worker script: %v", err))
		return
	}

	cmd := exec.Command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
		"-File", scriptPath, "-PkgRoot", pkgRoot, "-PgData", pgData, "-ResultPath", resultPath)
	_ = cmd.Run() // the script itself writes resultPath — this process has no console to report to
}
