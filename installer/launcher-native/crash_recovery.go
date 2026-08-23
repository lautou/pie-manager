// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// readPidFromFile parses a PID from the first line of path, tolerating trailing lines (matches
// PostgreSQL's own postmaster.pid lock-file format: PID on line 1, data directory on line 2,
// port on line 3, ... - but works identically for a plain single-line pid file too). Returns
// 0, false if the file doesn't exist or its first line isn't a valid integer.
func readPidFromFile(path string) (int, bool) {
	data, err := os.ReadFile(path)
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

// readPostmasterPid reads the PID Postgres itself recorded in postmaster.pid.
func readPostmasterPid(home string) (int, bool) {
	return readPidFromFile(postmasterPidPath(home))
}

// writePidRecord records pid and its own startTime (as returned by processStartTime right after
// spawning it - see backend.go's startBackend/startWorker) into path, one value per line. Unlike
// postmaster.pid, this file's format is entirely ours to define, which is what lets
// recoverOrphanedPythonProcess below verify a live process is genuinely the one this launcher
// spawned, not just a process that happens to exist under the same, possibly-recycled, PID.
func writePidRecord(path string, pid int, startTime uint64) error {
	return os.WriteFile(path, []byte(fmt.Sprintf("%d\n%d\n", pid, startTime)), 0o644)
}

// readPidRecord parses a pid+start-time record written by writePidRecord. Returns ok=false if
// the file is missing or malformed in any way (wrong line count, non-numeric field).
func readPidRecord(path string) (pid int, startTime uint64, ok bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, 0, false
	}
	lines := strings.Split(strings.TrimRight(string(data), "\n"), "\n")
	if len(lines) != 2 {
		return 0, 0, false
	}
	pid, pidErr := strconv.Atoi(lines[0])
	startTime, timeErr := strconv.ParseUint(lines[1], 10, 64)
	if pidErr != nil || timeErr != nil {
		return 0, 0, false
	}
	return pid, startTime, true
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

// recoverFromPreviousSession detects and cleans up postgres/backend/worker processes left
// running by a previous, uncleanly-terminated launcher session (a forced kill via Task Manager,
// the machine sleeping while the app was open, or an abrupt Windows shutdown — none of which
// #76's poc ever exercised, since every poc run ended in a clean, controlled shutdown).
//
// Must run before every startPostgres AND before stageBundledFiles (issue #119): once staging
// can delete+recopy pgsql/the Python interpreter on a bundle-id mismatch, os.RemoveAll fails on
// Windows if an orphaned postgres.exe/python.exe from a previous session still holds that
// directory open - an orphan must be located and terminated first, regardless of whether it's
// also blocking a fresh startPostgres.
func recoverFromPreviousSession(home string) error {
	if err := recoverOrphanedPostgres(home); err != nil {
		return err
	}
	if err := recoverOrphanedPythonProcess(backendPidPath(home)); err != nil {
		return err
	}
	if err := recoverOrphanedPythonProcess(workerPidPath(home)); err != nil {
		return err
	}
	return nil
}

// recoverOrphanedPostgres kills a postgres.exe left running by a previous session, identified by
// the PID Postgres itself recorded in postmaster.pid. Postgres's own WAL-based crash recovery
// already handles data-integrity concerns on its next start regardless of how it was stopped,
// and a stale (dead-PID) lock file is cleaned up by Postgres itself on its own next start — the
// gap this specifically closes is that a fresh pg_ctl start against the SAME pgdata directory
// fails outright while a previous postgres instance is still alive (Postgres enforces
// single-instance-per-data-directory locking via this same file).
//
// Unlike recoverOrphanedPythonProcess below, this cannot also verify the live process's start
// time before killing it — postmaster.pid's format is PostgreSQL's own, with no start-time field
// to compare against, and no record of postgres's own start time exists on our side to have
// captured in the first place (accepted narrow risk, same as isPidRunning's own doc comment: a
// recycled PID could false-positive here, same as it always could).
func recoverOrphanedPostgres(home string) error {
	pid, ok := readPostmasterPid(home)
	if !ok {
		return nil // no lock file at all - nothing to recover from
	}
	if !isPidRunning(pid) {
		return nil // stale lock file from an unclean shutdown; Postgres cleans this up itself
	}
	return killPid(pid, "postgres")
}

// recoverOrphanedPythonProcess kills a backend/worker python.exe left running by a previous
// session, identified by a pid+start-time record this launcher wrote itself when it originally
// spawned that process (see writePidRecord, called from startBackend/startWorker). Unlike
// postmaster.pid (recoverOrphanedPostgres), this file's format is entirely ours, so the live
// process's own current start time is checked against what was recorded before killing it -
// closing the PID-reuse false-positive gap isPidRunning's own doc comment accepts for Postgres,
// for the one case where inventing the file format ourselves makes that fully avoidable.
func recoverOrphanedPythonProcess(pidPath string) error {
	pid, recordedStart, ok := readPidRecord(pidPath)
	if !ok {
		return nil // no record at all - nothing to recover from
	}
	if !isPidRunning(pid) {
		return nil // stale record from a clean shutdown; nothing left to kill
	}
	liveStart, err := processStartTime(pid)
	if err != nil || liveStart != recordedStart {
		// Either the process exited between the liveness check above and here, or Windows has
		// recycled this pid onto an unrelated process since - not the one this launcher spawned,
		// so leave it alone rather than kill an innocent bystander process.
		return nil
	}
	return killPid(pid, "python")
}

// killPid terminates the process identified by pid, used by both recovery functions above -
// label only affects the wrapped error message, so a caller can tell which kind of orphan
// failed to terminate.
func killPid(pid int, label string) error {
	proc, err := os.FindProcess(pid)
	if err != nil {
		return nil // pid stopped existing between the caller's liveness check and here - already gone
	}
	if err := proc.Kill(); err != nil {
		return fmt.Errorf("terminating orphaned %s process (pid %d): %w", label, pid, err)
	}
	return nil
}
