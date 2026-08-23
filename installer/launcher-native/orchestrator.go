// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"context"
	"fmt"
	"os/exec"
	"time"
)

// healthTimeout bounds how long we wait for the backend to become reachable after spawning it.
const healthTimeout = 30 * time.Second

// nativeSession holds everything the orchestrator needs to clean up on shutdown.
type nativeSession struct {
	home       string
	ports      ports
	backendCmd *exec.Cmd
	workerCmd  *exec.Cmd
}

// startupSequence runs the full launch orchestration: data-directory setup, staging the
// package's bundled pgsql/python from its own read-only install directory, first-run detection,
// crash recovery, Postgres init/start, database creation on first run, and spawning the
// backend and the PgQueuer worker (issue #83).
//
// onProgress is called before each phase with a short, user-facing status string - main.go
// wires it to the loading screen's setStatus so a first run (which can take minutes: initdb,
// Windows Defender scanning the freshly-extracted Python interpreter, the full Alembic
// migration history) shows real step-by-step feedback instead of one static message the whole
// time (user-reported UX gap after #82/#83 shipped). May be nil (e.g. from a future test that
// doesn't care about progress reporting) - callers must not assume it's always set.
//
// It composes runInitdb/startPostgres/createAppDatabase/startBackend/startWorker/
// recoverFromPreviousSession - already-documented, intentionally-untestable process-spawning
// functions (see
// postgres.go/backend.go/crash_recovery.go) - so this function is itself not meaningfully
// unit-testable and is covered instead by the CI install+launch smoke test planned for this MVP
// (see issue #82's sequencing). This matches this project's own established policy for the
// existing Podman-based installer's equivalent orchestration functions (runInstall,
// runStartWithCompose in installer/install.go) - every individual decision this function makes
// (paths, args, port selection, first-run detection) is already extracted into separately
// tested, pure functions; this is deliberately kept as thin sequencing glue with no logic of
// its own worth testing in isolation.
func startupSequence(pkgRoot, home string, onProgress func(string)) (*nativeSession, error) {
	report := func(status string) {
		if onProgress != nil {
			onProgress(status)
		}
	}

	report("Preparing data directories…")
	if err := ensureDataDirs(home); err != nil {
		return nil, fmt.Errorf("preparing data directories: %w", err)
	}

	// Must run before stageBundledFiles, not after (issue #119): once staging can delete+recopy
	// pgsql/the Python interpreter on a bundle-id mismatch, os.RemoveAll fails on Windows if an
	// orphaned postgres.exe/python.exe from a previous, uncleanly-terminated session still holds
	// that directory open - any such orphan must be cleared out first.
	report("Checking for a previous session…")
	if err := recoverFromPreviousSession(home); err != nil {
		return nil, fmt.Errorf("recovering from a previous session: %w", err)
	}

	// Confirmed live (a real end-to-end test of this exact orchestration, before this fix):
	// initdb.exe fails with "fork/exec ... le fichier spécifié est introuvable" without this -
	// ensureDataDirs only creates empty directories, it never populates them from the package's
	// own bundled pgsql/python folders, which cannot execute in place from the package's
	// read-only install directory (confirmed in #76's poc for the same reason).
	report("Preparing application files…")
	if err := stageBundledFiles(pkgRoot, home); err != nil {
		return nil, fmt.Errorf("staging bundled files: %w", err)
	}

	firstRun := isFirstRun(home)

	p := selectPorts()

	if firstRun {
		report("Setting up local database (first run)…")
		if err := runInitdb(home); err != nil {
			return nil, fmt.Errorf("initializing database: %w", err)
		}
	}

	report("Starting local database…")
	postgresCmd, err := startPostgres(home, p.Postgres)
	if err != nil {
		return nil, fmt.Errorf("starting postgres: %w", err)
	}

	pgReadyCtx, pgReadyCancel := context.WithTimeout(context.Background(), processTimeout)
	defer pgReadyCancel()
	if err := waitForPostgresReady(pgReadyCtx, postgresCmd, home, p.Postgres); err != nil {
		return nil, fmt.Errorf("waiting for postgres to become ready: %w", err)
	}

	if firstRun {
		report("Creating application database (first run)…")
		if err := createAppDatabase(home, p.Postgres); err != nil {
			_ = stopPostgres(home)
			return nil, fmt.Errorf("creating application database: %w", err)
		}
	}

	// Every launch, not just first run - an app update carrying new migrations needs them
	// applied the next time the user opens the app, mirroring compose-prod.yaml's own
	// unconditional "alembic upgrade head && uvicorn" startup sequence.
	report("Updating local database…")
	if err := runMigrations(home, p.Postgres); err != nil {
		_ = stopPostgres(home)
		return nil, fmt.Errorf("applying database migrations: %w", err)
	}

	report("Starting backend service…")
	backendCmd, err := startBackend(home, p.Backend, p.Postgres)
	if err != nil {
		_ = stopPostgres(home)
		return nil, fmt.Errorf("starting backend: %w", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), healthTimeout)
	defer cancel()
	if err := waitForHealth(ctx, p.Backend); err != nil {
		_ = stopChildProcess(backendCmd)
		_ = stopPostgres(home)
		return nil, fmt.Errorf("waiting for backend to become healthy: %w", err)
	}

	// Started only once the backend is confirmed healthy - the worker's own schema/DB
	// dependency is already satisfied by runMigrations above regardless, but gating it on a
	// healthy backend means a worker-start failure is reported against a known-good baseline
	// rather than compounding with an already-uncertain backend state.
	report("Starting background worker…")
	workerCmd, err := startWorker(home, p.Postgres)
	if err != nil {
		_ = stopChildProcess(backendCmd)
		_ = stopPostgres(home)
		return nil, fmt.Errorf("starting worker: %w", err)
	}

	return &nativeSession{home: home, ports: p, backendCmd: backendCmd, workerCmd: workerCmd}, nil
}

// shutdown gracefully stops the worker and backend, then Postgres, in that order - both child
// processes should stop accepting/processing work before their database connection is torn out
// from under them. Called on window close. Safe to call on a nil session (e.g. if
// startupSequence itself failed before a session was ever created).
func (s *nativeSession) shutdown() {
	if s == nil {
		return
	}
	_ = stopChildProcess(s.workerCmd)
	_ = stopChildProcess(s.backendCmd)
	_ = stopPostgres(s.home)
}
