//go:build windows

// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"os/exec"
	"syscall"
)

// createNoWindow is CREATE_NO_WINDOW - not exported by the standard syscall package on Windows,
// so it's defined here from its documented Win32 value (Microsoft's Process Creation Flags
// reference).
const createNoWindow = 0x08000000

// hideWindow prevents a spawned console subprocess (postgres.exe, python.exe/uvicorn) from
// popping up its own visible console window. Without this, Windows allocates a new console for
// any console subprocess launched from a windowless GUI app (this launcher has no console of
// its own — built with -H windowsgui, see build-installer.yml) — confirmed live: 2 CMD windows
// appeared on every launch (one for the Postgres server, one for uvicorn), closing only when the
// app itself closed since both are long-lived child processes.
//
// CreationFlags: CREATE_NO_WINDOW, not just HideWindow alone. HideWindow only sets
// STARTUPINFO's STARTF_USESHOWWINDOW/SW_HIDE, which hides a console window *after* one gets
// allocated — it does not stop Windows from allocating one in the first place. That distinction
// matters specifically for Postgres: on Windows it has no fork(), so the postmaster relaunches
// itself via its own internal CreateProcess calls (EXEC_BACKEND) for every background worker
// (checkpointer, autovacuum launcher, etc.) — confirmed live, 7 separate postgres.exe processes
// for a single idle server. Those internal relaunches are Postgres's own C code, entirely outside
// our control, and a child with no console to inherit allocates a fresh, non-hidden one of its
// own regardless of what HideWindow did for the parent. CREATE_NO_WINDOW instead means the
// parent (the postmaster we spawn) never has a console at all - nothing for it or its own
// children to allocate one against - which is what actually suppresses the window for every
// EXEC_BACKEND worker too, not just the top-level process. HideWindow is kept alongside it as
// defense in depth for any code path that does end up needing a console handle.
func hideWindow(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: createNoWindow,
	}
}
