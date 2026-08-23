// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// copyFileContents copies the content of src into dst, creating/truncating dst.
func copyFileContents(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}

// copyTree recursively copies src to dst, creating directories as needed. Used to stage the
// package's own bundled pgsql/ and python/ folders (read-only, cannot execute in place from
// inside the MSIX's install directory - confirmed live in #76's poc) into this app's writable
// data directory. A native Go implementation, not a robocopy shell-out or PowerShell
// Copy-Item: the hang #76's poc hit with Copy-Item -Recurse on a many-small-files tree was
// specific to that PowerShell cmdlet's own implementation, not a general Windows filesystem
// behavior Go's plain os/io calls would have any reason to inherit.
func copyTree(src, dst string) error {
	return filepath.WalkDir(src, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return fmt.Errorf("walking %s: %w", path, err)
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return fmt.Errorf("computing relative path for %s: %w", path, err)
		}
		target := filepath.Join(dst, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		if err := copyFileContents(path, target); err != nil {
			return fmt.Errorf("copying %s to %s: %w", path, target, err)
		}
		return nil
	})
}

// pgsqlStagedMarker / pythonStagedMarker are files only present once a real staging copy has
// completed - used to skip re-copying ~130 MB of already-staged files on every subsequent
// launch, not just to detect first run (isFirstRun in paths.go answers a different question:
// whether Postgres itself has ever been initialized, which requires pgsql to already be staged
// - staging must always be checked independently, since a user could in principle delete just
// the staged pgsql/python folders without touching pgdata).
func pgsqlStagedMarker(home string) string  { return postgresExePath(home) }
func pythonStagedMarker(home string) string { return pythonExePath(home) }

// stageBundledFiles copies pgsql/, the Python interpreter, the backend's own app source, and
// frontend_dist/ from the package's own read-only install directory (pkgRoot) into this app's
// writable data directory. pgsql/the interpreter skip the copy if already staged; the backend
// app source and frontend_dist always re-stage (see below).
//
// pgsql/the Python interpreter+site-packages have no update/re-staging story yet (skipped
// entirely if the marker exists, regardless of whether the package itself was updated to a
// newer version with different bundled content) - matches this epic's own explicitly-deferred
// scope (issue #65: "no migration path... fresh-install only"). Tracked separately in #119: these
// are large (~150-250MB combined) and, unlike the app source below, don't actually change
// between releases in practice (PostgreSQL major version and the Python version are both
// project-wide pinned invariants), so a version-aware re-staging story is lower urgency.
//
// frontend_dist and the backend app source are the two exceptions, both fixed after real
// silent-staleness bugs were found in the field: frontend_dist after issue #118's follow-up
// investigation found every MSIX upgrade was silently still serving the very first version's
// frontend forever, and the backend app source (issue #121) after finding the same marker-skip
// check gated the FastAPI "app" package and Alembic migration scripts too - see
// stageBackendAppSource below. Both are small, rebuilt-every-release plain source/asset trees -
// cheap enough to unconditionally wipe and re-copy on every launch, which also guarantees no
// stale content-hashed asset file (e.g. an old index-XXXXXXXX.js) or removed migration script
// ever lingers alongside newer content.
func stageBundledFiles(pkgRoot, home string) error {
	if _, err := os.Stat(pgsqlStagedMarker(home)); os.IsNotExist(err) {
		if err := copyTree(filepath.Join(pkgRoot, "pgsql"), filepath.Join(dataDir(home), "pgsql")); err != nil {
			return fmt.Errorf("staging pgsql: %w", err)
		}
	}
	if _, err := os.Stat(pythonStagedMarker(home)); os.IsNotExist(err) {
		if err := copyTree(filepath.Join(pkgRoot, "python"), pythonDir(home)); err != nil {
			return fmt.Errorf("staging python: %w", err)
		}
	}
	if err := stageBackendAppSource(pkgRoot, home); err != nil {
		return err
	}
	if err := os.RemoveAll(frontendDistDir(home)); err != nil {
		return fmt.Errorf("clearing stale frontend_dist: %w", err)
	}
	if err := copyTree(filepath.Join(pkgRoot, "frontend_dist"), frontendDistDir(home)); err != nil {
		return fmt.Errorf("staging frontend_dist: %w", err)
	}
	return nil
}

// stageBackendAppSource copies the backend's own Python source (the "app" package) and its
// Alembic migrations from pkgRoot/python into backendAppDir, unconditionally on every launch -
// unlike the embeddable interpreter/site-packages they happen to be bundled alongside in the
// same pkgRoot/python tree (see build-installer.yml's packaging step, and backendAppDir's own
// doc comment in backend.go). Issue #121: gating this content behind the same "skip if
// python.exe already exists" marker as the interpreter meant a version bump's new endpoints or
// bugfixes were permanently invisible to an already-staged install, exactly like the
// frontend_dist bug above - and worse, since orchestrator.go's runMigrations runs "alembic
// upgrade head" against these exact staged scripts on every launch: a frozen alembic/ tree means
// a new migration is never applied at all for an existing user, not just never displayed.
func stageBackendAppSource(pkgRoot, home string) error {
	appDir := backendAppDir(home)
	if err := os.RemoveAll(filepath.Join(appDir, "app")); err != nil {
		return fmt.Errorf("clearing stale backend app source: %w", err)
	}
	if err := copyTree(filepath.Join(pkgRoot, "python", "app"), filepath.Join(appDir, "app")); err != nil {
		return fmt.Errorf("staging backend app source: %w", err)
	}
	if err := os.RemoveAll(filepath.Join(appDir, "alembic")); err != nil {
		return fmt.Errorf("clearing stale alembic migrations: %w", err)
	}
	if err := copyTree(filepath.Join(pkgRoot, "python", "alembic"), filepath.Join(appDir, "alembic")); err != nil {
		return fmt.Errorf("staging alembic migrations: %w", err)
	}
	if err := copyFileContents(filepath.Join(pkgRoot, "python", "alembic.ini"), filepath.Join(appDir, "alembic.ini")); err != nil {
		return fmt.Errorf("staging alembic.ini: %w", err)
	}
	return nil
}
