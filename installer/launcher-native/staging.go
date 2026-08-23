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

// stageBundledFiles copies pgsql/, python/, and frontend_dist/ from the package's own read-only
// install directory (pkgRoot) into this app's writable data directory. pgsql/python skip the
// copy if already staged; frontend_dist always re-stages (see below).
//
// pgsql/python have no update/re-staging story yet (skipped entirely if the marker exists,
// regardless of whether the package itself was updated to a newer version with different
// bundled content) - matches this epic's own explicitly-deferred scope (issue #65: "no
// migration path... fresh-install only"). Revisit once app-update handling is designed.
//
// frontend_dist is the one exception, fixed after issue #118's follow-up investigation found
// every MSIX upgrade in the field was silently still serving the very first version's frontend
// forever: this marker-skip check meant an updated package's new frontend_dist was never
// re-copied into the staged, writable directory the backend actually serves from, no matter how
// many versions had since shipped real fixes. Unlike pgsql/python (large one-time bundles,
// ~130MB, that don't change between releases), frontend_dist is small and rebuilt on every
// release - cheap enough to unconditionally wipe and re-copy on every launch, which also
// guarantees no stale content-hashed asset file (e.g. an old index-XXXXXXXX.js) ever lingers
// alongside a newer one.
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
	if err := os.RemoveAll(frontendDistDir(home)); err != nil {
		return fmt.Errorf("clearing stale frontend_dist: %w", err)
	}
	if err := copyTree(filepath.Join(pkgRoot, "frontend_dist"), frontendDistDir(home)); err != nil {
		return fmt.Errorf("staging frontend_dist: %w", err)
	}
	return nil
}
