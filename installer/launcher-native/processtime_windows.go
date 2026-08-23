//go:build windows

// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"fmt"
	"syscall"
)

// processStartTime returns the creation time Windows itself recorded for the process identified
// by pid, as a single opaque, monotonically-comparable value (raw 100-nanosecond-interval count
// since the Windows epoch, per GetProcessTimes' own Filetime output) - never meant to be
// interpreted as a calendar time, only ever compared for equality against a value recorded
// earlier for the same pid (see crash_recovery.go's writePidRecord/recoverOrphanedPythonProcess:
// this is what lets a later launch tell "the process I spawned is still running" apart from "an
// unrelated process now happens to have the same, recycled pid").
func processStartTime(pid int) (uint64, error) {
	h, err := syscall.OpenProcess(syscall.PROCESS_QUERY_INFORMATION, false, uint32(pid))
	if err != nil {
		return 0, fmt.Errorf("opening process %d: %w", pid, err)
	}
	defer syscall.CloseHandle(h)

	var creation, exit, kernel, user syscall.Filetime
	if err := syscall.GetProcessTimes(h, &creation, &exit, &kernel, &user); err != nil {
		return 0, fmt.Errorf("getting process times for %d: %w", pid, err)
	}
	return uint64(creation.HighDateTime)<<32 | uint64(creation.LowDateTime), nil
}
