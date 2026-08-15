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
}

// startupSequence runs the full launch orchestration: data-directory setup, first-run
// detection, crash recovery, Postgres init/start, database creation on first run, and spawning
// the backend.
//
// It composes runInitdb/startPostgres/createAppDatabase/startBackend/recoverFromPreviousSession
// - already-documented, intentionally-untestable process-spawning functions (see
// postgres.go/backend.go/crash_recovery.go) - so this function is itself not meaningfully
// unit-testable and is covered instead by the CI install+launch smoke test planned for this MVP
// (see issue #82's sequencing). This matches this project's own established policy for the
// existing Podman-based installer's equivalent orchestration functions (runInstall,
// runStartWithCompose in installer/install.go) - every individual decision this function makes
// (paths, args, port selection, first-run detection) is already extracted into separately
// tested, pure functions; this is deliberately kept as thin sequencing glue with no logic of
// its own worth testing in isolation.
func startupSequence(home string) (*nativeSession, error) {
	if err := ensureDataDirs(home); err != nil {
		return nil, fmt.Errorf("preparing data directories: %w", err)
	}

	firstRun := isFirstRun(home)

	if err := recoverFromPreviousSession(home); err != nil {
		return nil, fmt.Errorf("recovering from a previous session: %w", err)
	}

	p := selectPorts()

	if firstRun {
		if err := runInitdb(home); err != nil {
			return nil, fmt.Errorf("initializing database: %w", err)
		}
	}

	if err := startPostgres(home, p.Postgres); err != nil {
		return nil, fmt.Errorf("starting postgres: %w", err)
	}

	if firstRun {
		if err := createAppDatabase(home, p.Postgres); err != nil {
			_ = stopPostgres(home)
			return nil, fmt.Errorf("creating application database: %w", err)
		}
	}

	// Every launch, not just first run - an app update carrying new migrations needs them
	// applied the next time the user opens the app, mirroring compose-prod.yaml's own
	// unconditional "alembic upgrade head && uvicorn" startup sequence.
	if err := runMigrations(home, p.Postgres); err != nil {
		_ = stopPostgres(home)
		return nil, fmt.Errorf("applying database migrations: %w", err)
	}

	backendCmd, err := startBackend(home, p.Backend, p.Postgres)
	if err != nil {
		_ = stopPostgres(home)
		return nil, fmt.Errorf("starting backend: %w", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), healthTimeout)
	defer cancel()
	if err := waitForHealth(ctx, p.Backend); err != nil {
		_ = stopBackend(backendCmd)
		_ = stopPostgres(home)
		return nil, fmt.Errorf("waiting for backend to become healthy: %w", err)
	}

	return &nativeSession{home: home, ports: p, backendCmd: backendCmd}, nil
}

// shutdown gracefully stops the backend then Postgres, in that order - the backend should stop
// accepting new requests before its database connection is torn out from under it. Called on
// window close. Safe to call on a nil session (e.g. if startupSequence itself failed before a
// session was ever created).
func (s *nativeSession) shutdown() {
	if s == nil {
		return
	}
	_ = stopBackend(s.backendCmd)
	_ = stopPostgres(s.home)
}
