// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"os"
	"path/filepath"
)

// dataDirName is the folder created directly under the user's profile root, never under
// AppData/LocalAppData. Confirmed live (issue #82, github.com/lautou/pie-manager/issues/76's
// poc): a full-trust MSIX app's writes anywhere under AppData are transparently redirected to a
// private per-package location that Windows deletes when the package is uninstalled, even via a
// fully hardcoded path with no environment variable involved. Writes derived from the user's
// home directory, outside AppData entirely, are real and survive uninstall — the only place
// Postgres's data can safely live for a financial-data app.
const dataDirName = "PieManager"

// dataDir returns the app's persistent data directory: <home>\PieManager. home is injected
// (rather than this function calling os.UserHomeDir() itself) so it stays pure and testable;
// callers pass the real os.UserHomeDir() result.
func dataDir(home string) string {
	return filepath.Join(home, dataDirName)
}

// pgDataDir returns the PostgreSQL data directory under dataDir.
func pgDataDir(home string) string {
	return filepath.Join(dataDir(home), "pgdata")
}

// pgBinDir returns where the bundled pgsql/bin is staged under dataDir (the package's own
// read-only install directory cannot execute binaries in place — confirmed in the #76 poc — so
// pgsql must be copied into a writable location first, same as pgdata).
func pgBinDir(home string) string {
	return filepath.Join(dataDir(home), "pgsql", "bin")
}

// pythonDir returns where the bundled embeddable Python is staged under dataDir.
func pythonDir(home string) string {
	return filepath.Join(dataDir(home), "python")
}

// logDir returns where this app's own runtime logs (initdb/pg_ctl/uvicorn output) are kept.
func logDir(home string) string {
	return filepath.Join(dataDir(home), "logs")
}

// frontendDistDir returns where the built frontend (`vite build`'s `dist/` output) is staged
// under dataDir — passed to the backend as FRONTEND_DIST_DIR so it can serve it via
// app/frontend.py's mount_frontend (issue #82).
func frontendDistDir(home string) string {
	return filepath.Join(dataDir(home), "frontend_dist")
}

// pgVersionMarkerPath is the file initdb writes as part of a successful run. Its presence is
// used to detect whether Postgres has ever been initialized here, rather than merely checking
// whether the pgdata directory exists (a directory can exist empty after a partial/interrupted
// first run).
func pgVersionMarkerPath(home string) string {
	return filepath.Join(pgDataDir(home), "PG_VERSION")
}

// isFirstRun reports whether Postgres has never been successfully initialized under home.
func isFirstRun(home string) bool {
	_, err := os.Stat(pgVersionMarkerPath(home))
	return os.IsNotExist(err)
}

// postmasterPidPath is the file pg_ctl/postgres maintain while the server is running (or, if
// left behind by an unclean shutdown, an indicator of a possible crashed/orphaned instance).
func postmasterPidPath(home string) string {
	return filepath.Join(pgDataDir(home), "postmaster.pid")
}

// backendPidPath / workerPidPath are pid+start-time records this launcher writes itself right
// after spawning the backend/worker (see backend.go's startBackend/startWorker) - unlike
// postmasterPidPath above, whose format PostgreSQL itself owns, these are our own invention, so
// crash_recovery.go can verify a live process's start time still matches what was recorded
// before treating it as the same orphaned process to kill (see recoverOrphanedPythonProcess).
func backendPidPath(home string) string { return filepath.Join(dataDir(home), "backend.pid") }
func workerPidPath(home string) string  { return filepath.Join(dataDir(home), "worker.pid") }

// ensureDataDirs creates every directory this app writes to under dataDir, if not already
// present. Safe to call on every launch, not just first run.
func ensureDataDirs(home string) error {
	for _, d := range []string{dataDir(home), pgDataDir(home), pgBinDir(home), pythonDir(home), logDir(home), frontendDistDir(home)} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return err
		}
	}
	return nil
}
