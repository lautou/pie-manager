// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"bytes"
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

// pgsqlBundleIDPath / pythonBundleIDPath point at a small file build-installer.yml drops
// directly into the package, recording an identifier derived from that payload's actual build
// inputs (the pinned download URL for pgsql; the pinned Python version + a hash of
// requirements.txt for python - see that workflow's own comments). Deliberately NOT this app's
// own release Version (backend.go): Version changes on every single release regardless of
// whether pgsql/the interpreter+site-packages actually changed, which would force a needless
// ~150-250MB re-copy on every update if used here - the whole point of #119's version-aware
// re-staging is to only pay that cost when the bundled content itself actually changed.
func pgsqlBundleIDPath(pkgRoot string) string {
	return filepath.Join(pkgRoot, "pgsql", "bundle-id.txt")
}
func pythonBundleIDPath(pkgRoot string) string {
	return filepath.Join(pkgRoot, "python", "bundle-id.txt")
}

// pgsqlStagedBundleIDPath / pythonStagedBundleIDPath record, inside the writable data directory,
// which bundle-id was actually staged there - written only after copyTree fully succeeds (see
// stageIfBundleChanged), never before. This also closes a latent gap the old exe-presence-only
// marker had: filepath.WalkDir visits a directory's entries in lexical order, so pgsql's own
// bin/postgres.exe (alphabetically before lib/, share/) could already exist even after a copy
// interrupted partway through - the old marker would have misread that as "fully staged".
func pgsqlStagedBundleIDPath(home string) string {
	return filepath.Join(dataDir(home), "pgsql", "staged-bundle-id.txt")
}
func pythonStagedBundleIDPath(home string) string {
	return filepath.Join(pythonDir(home), "staged-bundle-id.txt")
}

// stageIfBundleChanged re-stages src into dst whenever the package's own bundle-id (read from
// bundleIDPath) differs from what's already recorded at stagedIDPath, or no id was ever
// recorded there at all - which also covers migrating an install that predates this mechanism
// (issue #119): such an install has no staged-bundle-id.txt file, so its first launch after this
// fix ships pays one unavoidable full re-stage even if pgsql/the interpreter didn't actually
// change, purely because there was previously no way to tell.
func stageIfBundleChanged(src, dst, bundleIDPath, stagedIDPath string) error {
	wantID, err := os.ReadFile(bundleIDPath)
	if err != nil {
		return fmt.Errorf("reading bundle id from package: %w", err)
	}
	gotID, _ := os.ReadFile(stagedIDPath) // missing/unreadable => empty => always mismatches below
	if bytes.Equal(wantID, gotID) {
		return nil
	}
	if err := os.RemoveAll(dst); err != nil {
		return fmt.Errorf("clearing stale content before re-staging: %w", err)
	}
	if err := copyTree(src, dst); err != nil {
		return fmt.Errorf("copying: %w", err)
	}
	if err := os.WriteFile(stagedIDPath, wantID, 0o644); err != nil {
		return fmt.Errorf("recording staged bundle id: %w", err)
	}
	return nil
}

// stageBundledFiles copies pgsql/, the Python interpreter, the backend's own app source, and
// frontend_dist/ from the package's own read-only install directory (pkgRoot) into this app's
// writable data directory. pgsql/the interpreter re-stage only when their bundle-id changed
// (see stageIfBundleChanged); the backend app source and frontend_dist always re-stage (below).
//
// pgsql/the Python interpreter+site-packages are large (~150-250MB combined) and, unlike the app
// source below, only rarely actually change between releases (PostgreSQL/Python versions are
// project-wide pinned invariants, and requirements.txt only moves on a Dependabot bump) - so
// gating them behind a real content-based check, rather than unconditionally re-copying like
// frontend_dist, avoids paying that cost on every ordinary release.
//
// frontend_dist and the backend app source always re-stage unconditionally, after real
// silent-staleness bugs were found in the field: frontend_dist after issue #118's follow-up
// investigation found every MSIX upgrade was silently still serving the very first version's
// frontend forever, and the backend app source (issue #121) after finding the old exe-presence
// marker gated the FastAPI "app" package and Alembic migration scripts too - see
// stageBackendAppSource below. Both are small, rebuilt-every-release plain source/asset trees -
// cheap enough to unconditionally wipe and re-copy on every launch, which also guarantees no
// stale content-hashed asset file (e.g. an old index-XXXXXXXX.js) or removed migration script
// ever lingers alongside newer content.
func stageBundledFiles(pkgRoot, home string) error {
	if err := stageIfBundleChanged(
		filepath.Join(pkgRoot, "pgsql"), filepath.Join(dataDir(home), "pgsql"),
		pgsqlBundleIDPath(pkgRoot), pgsqlStagedBundleIDPath(home),
	); err != nil {
		return fmt.Errorf("staging pgsql: %w", err)
	}
	// Re-staging the interpreter here (on a bundle-id mismatch) also wipes and recreates app/
	// alembic/alembic.ini, since pkgRoot/python bundles them all in one tree (see
	// build-installer.yml's packaging step) - harmless, stageBackendAppSource below
	// unconditionally re-copies them again immediately after regardless.
	if err := stageIfBundleChanged(
		filepath.Join(pkgRoot, "python"), pythonDir(home),
		pythonBundleIDPath(pkgRoot), pythonStagedBundleIDPath(home),
	); err != nil {
		return fmt.Errorf("staging python: %w", err)
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
