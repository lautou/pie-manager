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

// frontendDistStagedMarker uses index.html rather than a marker file of its own - vite build's
// output always includes one at the dist root, so no extra file needs to ship in the package
// purely to serve as a marker.
func frontendDistStagedMarker(home string) string {
	return filepath.Join(frontendDistDir(home), "index.html")
}

// stageBundledFiles copies pgsql/, python/, and frontend_dist/ from the package's own read-only
// install directory (pkgRoot) into this app's writable data directory, skipping any of the
// three copies whose marker file is already present.
//
// Note: this MVP has no update/re-staging story yet (skipped entirely if the marker exists,
// regardless of whether the package itself was updated to a newer version with different
// bundled content) - matches this epic's own explicitly-deferred scope (issue #65: "no
// migration path... fresh-install only"). Revisit once app-update handling is designed.
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
	if _, err := os.Stat(frontendDistStagedMarker(home)); os.IsNotExist(err) {
		if err := copyTree(filepath.Join(pkgRoot, "frontend_dist"), frontendDistDir(home)); err != nil {
			return fmt.Errorf("staging frontend_dist: %w", err)
		}
	}
	return nil
}
