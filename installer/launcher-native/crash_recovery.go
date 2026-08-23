// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// readPostmasterPid parses the PID from the first line of postmaster.pid, per PostgreSQL's own
// documented lock-file format (PID on line 1, data directory on line 2, port on line 3, ...).
// Returns 0, false if the file doesn't exist or its first line isn't a valid integer.
func readPostmasterPid(home string) (int, bool) {
	data, err := os.ReadFile(postmasterPidPath(home))
	if err != nil {
		return 0, false
	}
	lines := strings.SplitN(string(data), "\n", 2)
	pid, convErr := strconv.Atoi(strings.TrimSpace(lines[0]))
	if convErr != nil {
		return 0, false
	}
	return pid, true
}

// isPidRunning reports whether a process with the given PID currently exists. On Windows,
// os.FindProcess actually opens a real handle to the process (unlike POSIX, where FindProcess
// always succeeds regardless of whether the PID exists) — a real, if imperfect, liveness check.
// Narrow, accepted edge case for this MVP: if the original process already died and Windows has
// since recycled that exact PID number for an unrelated process, this reports a false positive.
// A fully precise check would additionally verify the process image name via a Win32 API call
// (QueryFullProcessImageName) - not worth the added complexity unless this proves to matter in
// practice.
func isPidRunning(pid int) bool {
	proc, err := os.FindProcess(pid)
	return err == nil && proc != nil
}

// recoverFromPreviousSession detects and cleans up a Postgres server left running by a
// previous, uncleanly-terminated launcher session (a forced kill via Task Manager, the machine
// sleeping while the app was open, or an abrupt Windows shutdown — none of which #76's poc ever
// exercised, since every poc run ended in a clean, controlled shutdown). Postgres's own
// WAL-based crash recovery already handles data-integrity concerns on its next start regardless
// of how it was stopped, and a stale (dead-PID) lock file is cleaned up by Postgres itself on
// its own next start — the gap this specifically closes is that a fresh pg_ctl start against
// the SAME pgdata directory fails outright while a previous postgres instance is still alive
// (Postgres enforces single-instance-per-data-directory locking via this same file), so a live
// orphan must be located and terminated before this session's own startPostgres call.
//
// Must be called before every startPostgres, not just after detecting a crash - there is no
// cheaper reliable way to distinguish "clean previous shutdown" from "crash" than checking
// whether the recorded PID is still alive.
func recoverFromPreviousSession(home string) error {
	pid, ok := readPostmasterPid(home)
	if !ok {
		return nil // no lock file at all - nothing to recover from
	}
	if !isPidRunning(pid) {
		return nil // stale lock file from an unclean shutdown; Postgres cleans this up itself
	}
	proc, err := os.FindProcess(pid)
	if err != nil {
		return nil // pid stopped existing between the check above and here - already gone
	}
	if err := proc.Kill(); err != nil {
		return fmt.Errorf("terminating orphaned postgres process (pid %d): %w", pid, err)
	}
	return nil
}
