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
	"strings"
)

func writeResult(resultPath, body string) {
	_ = os.WriteFile(resultPath, []byte(body), 0o644)
}

// runPersistenceTest answers a question none of this poc's other checks ever needed: does a
// full-trust MSIX app's write to a path OUTSIDE its own package-scoped LocalState/AppData
// storage actually persist as a real file that survives package uninstall? LocalState is known
// to be wiped on uninstall — fine for throwaway poc data, not acceptable for a real app's
// financial data. Two candidate paths are tested to isolate two independent questions:
//   - pathA is built from USERPROFILE at runtime, landing outside AppData entirely (matches
//     Microsoft's own documented behavior: "Read/Write operations to files and folders that are
//     not part of the package or VFS mapping are not controlled by the container" — Documents
//     and other non-AppData profile folders are explicitly called out as one example).
//   - pathB is a fully hardcoded literal string with NO environment variable involved at all,
//     landing physically under AppData\Local — this tests whether MSIX's AppData redirection
//     ("All writes to the user's AppData folder... are copied on write to a private per-user,
//     per-app location") is a raw-path-level interception (would still catch pathB) or merely an
//     environment-variable substitution trick (pathB would bypass it). pathBMirror checks the
//     documented private-copy destination directly, so a redirected pathB shows exactly where
//     its data actually went instead of just "not here."
func runPersistenceTest() []string {
	var lines []string
	lines = append(lines, "--- PERSISTENCE_TEST ---")

	userProfile := os.Getenv("USERPROFILE")
	localAppData := os.Getenv("LOCALAPPDATA")
	appData := os.Getenv("APPDATA")
	temp := os.Getenv("TEMP")
	lines = append(lines, fmt.Sprintf("ENV_USERPROFILE: %s", userProfile))
	lines = append(lines, fmt.Sprintf("ENV_LOCALAPPDATA: %s", localAppData))
	lines = append(lines, fmt.Sprintf("ENV_APPDATA: %s", appData))
	lines = append(lines, fmt.Sprintf("ENV_TEMP: %s", temp))

	homeDir, homeErr := os.UserHomeDir()
	lines = append(lines, fmt.Sprintf("GO_USERHOMEDIR: %s (err: %v)", homeDir, homeErr))

	writeMarker := func(label, path, content string) {
		mkdirErr := os.MkdirAll(filepath.Dir(path), 0o755)
		var writeErr error
		if mkdirErr == nil {
			writeErr = os.WriteFile(path, []byte(content), 0o644)
		}
		lines = append(lines, fmt.Sprintf("%s_PATH: %s", label, path))
		lines = append(lines, fmt.Sprintf("%s_MKDIR_ERROR: %v", label, mkdirErr))
		lines = append(lines, fmt.Sprintf("%s_WRITE_ERROR: %v", label, writeErr))
	}

	pathA := filepath.Join(homeDir, "PieManagerPersistTest", "marker_a.txt")
	writeMarker("PATH_A", pathA, "PERSIST_TEST_A_OK")

	// Deliberately not filepath.Join(localAppData, ...) or any env-var-derived value — a raw
	// literal string, matching the account confirmed earlier in this investigation ("pie").
	pathB := `C:\Users\pie\AppData\Local\PieManagerPersistTest\marker_b.txt`
	writeMarker("PATH_B", pathB, "PERSIST_TEST_B_OK")

	// Where Microsoft's own docs say an AppData write actually lands for a packaged app:
	// %LocalAppData%\Packages\<PackageFamilyName>\LocalCache\Local\... — check directly whether
	// pathB's content ended up here instead, rather than leaving "pathB wasn't at the literal
	// location" as an unexplained negative result.
	matches, _ := filepath.Glob(filepath.Join(localAppData, "Packages", "PieManagerMsixPostgresElevationPoc_*", "LocalCache", "Local", "PieManagerPersistTest", "marker_b.txt"))
	lines = append(lines, fmt.Sprintf("PATH_B_MIRROR_CANDIDATES: %v", matches))
	for _, m := range matches {
		content, readErr := os.ReadFile(m)
		lines = append(lines, fmt.Sprintf("PATH_B_MIRROR_CONTENT(%s): %s (err: %v)", m, string(content), readErr))
	}

	return lines
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

	// Runs and writes its own result file before anything else below - independent of, and not
	// gated on, the Postgres/PgQueuer/webserver checks that follow.
	persistLines := runPersistenceTest()
	writeResult(filepath.Join(localState, "persist_test.txt"), strings.Join(persistLines, "\n"))

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
