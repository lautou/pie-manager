// Command poc is a throwaway diagnostic build for issue #76 — see ../README.md. It never
// ships in the real product. Packaged as a full-trust MSIX and launched via its AUMID, it has
// no console attached, so all it does is resolve its own package paths, write out the worker
// PowerShell script (embedded below) to a file inside its own writable LocalState folder, run
// it with those paths as parameters, and exit. PowerShell is used for the actual test logic
// instead of raw Win32 syscalls from Go specifically so the measurement
// ([Security.Principal.WindowsPrincipal]::IsInRole(Administrator)) is a well-known, widely used
// one-liner — not a hand-rolled token/SID syscall wrapper with no local Windows dev loop to
// iterate against. The worker is invoked via -File (a temp .ps1), not -Command with an inline
// string, so package paths containing spaces (e.g. under "C:\Program Files\WindowsApps\...")
// never need manual command-line quoting.
//
// The result file (and the worker script itself) live under this package's own
// %LocalAppData%\Packages\<PFN>\LocalState\ folder, NOT %TEMP%. A first attempt used %TEMP%
// and the result file never appeared: %TEMP% sits under %LOCALAPPDATA%, which MSIX's
// filesystem virtualization silently redirects for a running full-trust package — so the
// packaged app's own view of "%TEMP%\foo" and the outside driving script's view of the same
// literal path are not necessarily the same physical file. LocalState is the one folder
// that's guaranteed identical from both sides (it's the real, non-redirected destination
// everything else redirects *into*), which is exactly why it's also used for pgdata below.
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
	exePath, err := os.Executable()
	if err != nil {
		// No writable, externally-visible location resolved yet at this point — nothing to do
		// but exit; the driving script's own timeout will report this as a silent failure.
		return
	}
	pkgRoot := filepath.Dir(exePath)

	localAppData := os.Getenv("LOCALAPPDATA")
	matches, _ := filepath.Glob(filepath.Join(localAppData, "Packages", "PieManagerMsixPostgresElevationPoc_*"))
	if len(matches) == 0 {
		return
	}
	localState := filepath.Join(matches[0], "LocalState")
	if err := os.MkdirAll(localState, 0o755); err != nil {
		return
	}
	resultPath := filepath.Join(localState, "result.txt")
	pgData := filepath.Join(localState, "pgdata")

	scriptPath := filepath.Join(localState, "worker.ps1")
	if err := os.WriteFile(scriptPath, []byte(workerScript), 0o644); err != nil {
		writeResult(resultPath, fmt.Sprintf("FAILURE: could not write worker script: %v", err))
		return
	}

	// Absolute path, not bare "powershell.exe": a process launched via package activation
	// (shell:AppsFolder / AUMID) may not inherit the same PATH a normal desktop-launched
	// process would, and os/exec does not search the current directory. Resolving via
	// %SystemRoot% sidesteps that PATH-resolution ambiguity entirely.
	psExe := filepath.Join(os.Getenv("SystemRoot"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	if _, err := os.Stat(psExe); err != nil {
		psExe = "powershell.exe" // fall back to PATH resolution if the well-known path is ever wrong
	}

	// Write a marker before attempting the launch, and capture Run()'s own error plus the
	// child's combined stdout/stderr explicitly (previously discarded via `_ = cmd.Run()`) —
	// so a launch failure, or the worker script itself erroring out before reaching its own
	// Set-Content, leaves the actual PowerShell error text in resultPath instead of either no
	// file appearing at all, or a bare unhelpful "exit status 1" with no message.
	writeResult(resultPath, fmt.Sprintf("STARTED: about to launch %s\n", psExe))
	cmd := exec.Command(psExe, "-NoProfile", "-ExecutionPolicy", "Bypass",
		"-File", scriptPath, "-PkgRoot", pkgRoot, "-PgData", pgData, "-ResultPath", resultPath)
	output, err := cmd.CombinedOutput()
	if err != nil {
		writeResult(resultPath, fmt.Sprintf("FAILURE: launching worker script failed: %v (psExe=%s)\n--- COMBINED_OUTPUT ---\n%s",
			err, psExe, string(output)))
	}
	// On success, the worker script itself has already overwritten resultPath with the real
	// VERDICT — nothing left to do here.
}
