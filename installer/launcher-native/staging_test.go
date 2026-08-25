// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func writeTestFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

// lockDirectory populates dir with a file then strips its permission bits, making it
// un-removable by os.RemoveAll (a permission-stripped directory can't be traversed/deleted) -
// shared by every "existing destination cannot be cleared" test below. Restores permissions via
// t.Cleanup so t.TempDir()'s own cleanup can still remove it afterward.
func lockDirectory(t *testing.T, dir string) {
	t.Helper()
	writeTestFile(t, filepath.Join(dir, "file.txt"), "content")
	if err := os.Chmod(dir, 0); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(dir, 0o755) })
}

// writeBackendAppSourceFixtures populates pkgRoot/python's app/alembic content - shared by every
// stageBundledFiles test below that needs to get past stageBackendAppSource to exercise a
// different step, plus the "happy path" stageBackendAppSource test itself.
func writeBackendAppSourceFixtures(t *testing.T, pkgRoot string) {
	t.Helper()
	writeTestFile(t, filepath.Join(pkgRoot, "python", "app", "main.py"), "app-source")
	writeTestFile(t, filepath.Join(pkgRoot, "python", "alembic", "versions", "0001_init.py"), "migration")
	writeTestFile(t, filepath.Join(pkgRoot, "python", "alembic.ini"), "[alembic]")
}

// writePgsqlFixture / writePythonFixture populate pkgRoot with a real pgsql/python payload plus
// its bundle-id.txt manifest (see staging.go's pgsqlBundleIDPath/pythonBundleIDPath) - shared by
// every stageBundledFiles test below that needs pgsql/python to stage (or skip) successfully in
// order to exercise a different, later step.
func writePgsqlFixture(t *testing.T, pkgRoot, bundleID string) {
	t.Helper()
	writeTestFile(t, filepath.Join(pkgRoot, "pgsql", "bin", "postgres.exe"), "pg-binary")
	writeTestFile(t, pgsqlBundleIDPath(pkgRoot), bundleID)
}

func writePythonFixture(t *testing.T, pkgRoot, bundleID string) {
	t.Helper()
	writeTestFile(t, filepath.Join(pkgRoot, "python", "python.exe"), "py-binary")
	writeTestFile(t, pythonBundleIDPath(pkgRoot), bundleID)
}

func TestCopyFileContents(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src.txt")
	dst := filepath.Join(dir, "dst.txt")
	writeTestFile(t, src, "hello world")

	if err := copyFileContents(src, dst); err != nil {
		t.Fatalf("copyFileContents failed: %v", err)
	}
	got, err := os.ReadFile(dst)
	if err != nil {
		t.Fatalf("expected dst to exist: %v", err)
	}
	if string(got) != "hello world" {
		t.Errorf("dst content = %q, want %q", string(got), "hello world")
	}
}

func TestCopyFileContents_ErrorMissingSrc(t *testing.T) {
	dir := t.TempDir()
	if err := copyFileContents(filepath.Join(dir, "missing.txt"), filepath.Join(dir, "dst.txt")); err == nil {
		t.Error("expected an error for a missing source file")
	}
}

func TestCopyFileContents_ErrorDstIsDir(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src.txt")
	writeTestFile(t, src, "content")
	dstDir := filepath.Join(dir, "dstdir")
	if err := os.MkdirAll(dstDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := copyFileContents(src, dstDir); err == nil {
		t.Error("expected an error when dst is an existing directory")
	}
}

func TestCopyTree_CopiesNestedStructure(t *testing.T) {
	src := t.TempDir()
	dst := filepath.Join(t.TempDir(), "dst")

	writeTestFile(t, filepath.Join(src, "bin", "postgres.exe"), "binary-content")
	writeTestFile(t, filepath.Join(src, "share", "postgres.bki"), "share-content")
	writeTestFile(t, filepath.Join(src, "lib", "nested", "deep.dll"), "deep-content")

	if err := copyTree(src, dst); err != nil {
		t.Fatalf("copyTree failed: %v", err)
	}

	for path, want := range map[string]string{
		filepath.Join(dst, "bin", "postgres.exe"):       "binary-content",
		filepath.Join(dst, "share", "postgres.bki"):     "share-content",
		filepath.Join(dst, "lib", "nested", "deep.dll"): "deep-content",
	} {
		got, err := os.ReadFile(path)
		if err != nil {
			t.Errorf("expected %s to exist: %v", path, err)
			continue
		}
		if string(got) != want {
			t.Errorf("%s content = %q, want %q", path, string(got), want)
		}
	}
}

func TestCopyTree_ErrorWhenDestinationFileBlockedByDirectory(t *testing.T) {
	src := t.TempDir()
	dst := filepath.Join(t.TempDir(), "dst")

	writeTestFile(t, filepath.Join(src, "file.txt"), "content")
	// Pre-create the destination path as a directory - copyFileContents' os.Create then fails
	// because you cannot open a directory for writing.
	if err := os.MkdirAll(filepath.Join(dst, "file.txt"), 0o755); err != nil {
		t.Fatal(err)
	}

	if err := copyTree(src, dst); err == nil {
		t.Error("expected an error when a destination file path is blocked by an existing directory")
	}
}

func TestCopyTree_ErrorMissingSrc(t *testing.T) {
	dst := t.TempDir()
	if err := copyTree(filepath.Join(dst, "does-not-exist"), filepath.Join(dst, "dst")); err == nil {
		t.Error("expected an error for a missing source tree")
	}
}

func TestStageIfBundleChanged_StagesOnFirstCall(t *testing.T) {
	src := t.TempDir()
	dst := filepath.Join(t.TempDir(), "dst")
	writeTestFile(t, filepath.Join(src, "bin", "tool.exe"), "content")
	bundleIDPath := filepath.Join(t.TempDir(), "bundle-id.txt")
	writeTestFile(t, bundleIDPath, "v1")
	stagedIDPath := filepath.Join(dst, "staged-bundle-id.txt")

	if err := stageIfBundleChanged(src, dst, bundleIDPath, stagedIDPath); err != nil {
		t.Fatalf("stageIfBundleChanged failed: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(dst, "bin", "tool.exe"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "content" {
		t.Errorf("bin/tool.exe content = %q, want %q", string(got), "content")
	}
	gotID, err := os.ReadFile(stagedIDPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(gotID) != "v1" {
		t.Errorf("staged bundle id = %q, want %q", string(gotID), "v1")
	}
}

func TestStageIfBundleChanged_SkipsWhenBundleIDUnchanged(t *testing.T) {
	// src has no real content at all - if stageIfBundleChanged tried to copy anyway, it would
	// fail, so a clean pass here proves the skip-when-unchanged branch fired.
	src := filepath.Join(t.TempDir(), "does-not-exist")
	dst := t.TempDir()
	bundleIDPath := filepath.Join(t.TempDir(), "bundle-id.txt")
	writeTestFile(t, bundleIDPath, "v1")
	stagedIDPath := filepath.Join(dst, "staged-bundle-id.txt")
	writeTestFile(t, stagedIDPath, "v1")

	if err := stageIfBundleChanged(src, dst, bundleIDPath, stagedIDPath); err != nil {
		t.Fatalf("stageIfBundleChanged failed: %v", err)
	}
}

func TestStageIfBundleChanged_RestagesWhenBundleIDChanged(t *testing.T) {
	src := t.TempDir()
	writeTestFile(t, filepath.Join(src, "bin", "tool.exe"), "new content")
	dst := t.TempDir()
	// A previously-staged file that's since been removed from the package entirely - proves
	// re-staging really wipes dst first, not just overlays new content onto the old tree.
	writeTestFile(t, filepath.Join(dst, "bin", "removed-tool.exe"), "gone now")
	bundleIDPath := filepath.Join(t.TempDir(), "bundle-id.txt")
	writeTestFile(t, bundleIDPath, "v2")
	stagedIDPath := filepath.Join(dst, "staged-bundle-id.txt")
	writeTestFile(t, stagedIDPath, "v1")

	if err := stageIfBundleChanged(src, dst, bundleIDPath, stagedIDPath); err != nil {
		t.Fatalf("stageIfBundleChanged failed: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(dst, "bin", "tool.exe"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "new content" {
		t.Errorf("bin/tool.exe content = %q, want %q", string(got), "new content")
	}
	if _, err := os.Stat(filepath.Join(dst, "bin", "removed-tool.exe")); !os.IsNotExist(err) {
		t.Error("expected the file removed from the new bundle to be gone after re-staging")
	}
	gotID, err := os.ReadFile(stagedIDPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(gotID) != "v2" {
		t.Errorf("staged bundle id = %q, want %q", string(gotID), "v2")
	}
}

func TestStageIfBundleChanged_RestagesWhenNoStagedIDExistsYet(t *testing.T) {
	// Reproduces migrating an install that predates issue #119 - real content already staged
	// (the old exe-presence marker this launcher used to rely on) but no staged-bundle-id.txt file
	// at all, since that concept didn't exist yet.
	src := t.TempDir()
	writeTestFile(t, filepath.Join(src, "bin", "tool.exe"), "new content")
	dst := t.TempDir()
	writeTestFile(t, filepath.Join(dst, "bin", "tool.exe"), "old content")
	bundleIDPath := filepath.Join(t.TempDir(), "bundle-id.txt")
	writeTestFile(t, bundleIDPath, "v1")
	stagedIDPath := filepath.Join(dst, "staged-bundle-id.txt")

	if err := stageIfBundleChanged(src, dst, bundleIDPath, stagedIDPath); err != nil {
		t.Fatalf("stageIfBundleChanged failed: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(dst, "bin", "tool.exe"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "new content" {
		t.Errorf("expected a pre-#119 install with no staged bundle id to be migrated, got %q", string(got))
	}
}

func TestStageIfBundleChanged_ErrorWhenBundleIDFileMissing(t *testing.T) {
	src := t.TempDir()
	dst := t.TempDir()
	bundleIDPath := filepath.Join(t.TempDir(), "bundle-id.txt") // never written
	stagedIDPath := filepath.Join(dst, "staged-bundle-id.txt")

	if err := stageIfBundleChanged(src, dst, bundleIDPath, stagedIDPath); err == nil {
		t.Error("expected an error when the package carries no bundle id at all")
	}
}

func TestStageIfBundleChanged_ErrorWhenSourceMissing(t *testing.T) {
	src := filepath.Join(t.TempDir(), "does-not-exist")
	dst := t.TempDir()
	bundleIDPath := filepath.Join(t.TempDir(), "bundle-id.txt")
	writeTestFile(t, bundleIDPath, "v1")
	stagedIDPath := filepath.Join(dst, "staged-bundle-id.txt")
	writeTestFile(t, stagedIDPath, "some-other-version") // forces the mismatch branch to run

	if err := stageIfBundleChanged(src, dst, bundleIDPath, stagedIDPath); err == nil {
		t.Error("expected an error when the source tree is missing")
	}
}

func TestStageIfBundleChanged_ErrorWhenDestinationCannotBeCleared(t *testing.T) {
	src := t.TempDir()
	writeTestFile(t, filepath.Join(src, "bin", "tool.exe"), "content")
	dst := t.TempDir()
	lockDirectory(t, filepath.Join(dst, "locked"))
	bundleIDPath := filepath.Join(t.TempDir(), "bundle-id.txt")
	writeTestFile(t, bundleIDPath, "v2")
	stagedIDPath := filepath.Join(dst, "staged-bundle-id.txt")
	writeTestFile(t, stagedIDPath, "v1")

	if err := stageIfBundleChanged(src, dst, bundleIDPath, stagedIDPath); err == nil {
		t.Error("expected an error when the existing destination cannot be cleared")
	}
}

func TestStageIfBundleChanged_ErrorWhenStagedIDCannotBeWritten(t *testing.T) {
	src := t.TempDir()
	writeTestFile(t, filepath.Join(src, "bin", "tool.exe"), "content")
	dst := t.TempDir()
	bundleIDPath := filepath.Join(t.TempDir(), "bundle-id.txt")
	writeTestFile(t, bundleIDPath, "v1")
	// A subdirectory copyTree never creates (src has no "no-such-dir") - os.WriteFile doesn't
	// create missing parent directories, so writing here fails cleanly after a successful copy.
	stagedIDPath := filepath.Join(dst, "no-such-dir", "staged-bundle-id.txt")

	if err := stageIfBundleChanged(src, dst, bundleIDPath, stagedIDPath); err == nil {
		t.Error("expected an error when the staged bundle id cannot be written")
	}
	if _, err := os.Stat(filepath.Join(dst, "bin", "tool.exe")); err != nil {
		t.Errorf("expected the copy itself to have already succeeded: %v", err)
	}
}

func TestStageBundledFiles_StagesEverythingOnFirstCall(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()

	writePgsqlFixture(t, pkgRoot, "postgresql-16.14")
	writePythonFixture(t, pkgRoot, "3.14.0|abc123")
	writeBackendAppSourceFixtures(t, pkgRoot)
	writeTestFile(t, filepath.Join(pkgRoot, "frontend_dist", "index.html"), "<html></html>")

	if err := stageBundledFiles(pkgRoot, home); err != nil {
		t.Fatalf("stageBundledFiles failed: %v", err)
	}

	if _, err := os.Stat(postgresExePath(home)); err != nil {
		t.Errorf("expected pgsql to be staged: %v", err)
	}
	if _, err := os.Stat(pythonExePath(home)); err != nil {
		t.Errorf("expected python to be staged: %v", err)
	}
	if _, err := os.Stat(filepath.Join(backendAppDir(home), "app", "main.py")); err != nil {
		t.Errorf("expected the backend app source to be staged: %v", err)
	}
	if _, err := os.Stat(filepath.Join(backendAppDir(home), "alembic.ini")); err != nil {
		t.Errorf("expected alembic.ini to be staged: %v", err)
	}
	if _, err := os.Stat(filepath.Join(frontendDistDir(home), "index.html")); err != nil {
		t.Errorf("expected frontend_dist to be staged: %v", err)
	}

	gotPgID, err := os.ReadFile(pgsqlStagedBundleIDPath(home))
	if err != nil {
		t.Fatal(err)
	}
	if string(gotPgID) != "postgresql-16.14" {
		t.Errorf("staged pgsql bundle id = %q, want %q", string(gotPgID), "postgresql-16.14")
	}
	gotPyID, err := os.ReadFile(pythonStagedBundleIDPath(home))
	if err != nil {
		t.Fatal(err)
	}
	if string(gotPyID) != "3.14.0|abc123" {
		t.Errorf("staged python bundle id = %q, want %q", string(gotPyID), "3.14.0|abc123")
	}
}

func TestStageBundledFiles_SkipsPgsqlAndPythonWhenBundleIDUnchanged(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()

	// Only the bundle-id.txt manifests exist under pkgRoot - no real pgsql/bin or python.exe
	// content at all. If stageBundledFiles tried to copy either anyway, it would fail, so a
	// clean pass here proves the skip-when-unchanged branch fired for both.
	writeTestFile(t, pgsqlBundleIDPath(pkgRoot), "postgresql-16.14")
	writeTestFile(t, pythonBundleIDPath(pkgRoot), "3.14.0|abc123")
	writeBackendAppSourceFixtures(t, pkgRoot)
	writeTestFile(t, filepath.Join(pkgRoot, "frontend_dist", "index.html"), "<html></html>")

	writeTestFile(t, pgsqlStagedBundleIDPath(home), "postgresql-16.14")
	writeTestFile(t, pythonStagedBundleIDPath(home), "3.14.0|abc123")

	if err := stageBundledFiles(pkgRoot, home); err != nil {
		t.Fatalf("stageBundledFiles failed: %v", err)
	}

	got, err := os.ReadFile(pgsqlStagedBundleIDPath(home))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "postgresql-16.14" {
		t.Errorf("expected the pre-staged pgsql bundle id to survive untouched, got %q", string(got))
	}
}

func TestStageBundledFiles_RestagesPgsqlAndPythonWhenBundleIDChanged(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()

	writePgsqlFixture(t, pkgRoot, "postgresql-16.15")
	writePythonFixture(t, pkgRoot, "3.14.1|def456")
	writeBackendAppSourceFixtures(t, pkgRoot)
	writeTestFile(t, filepath.Join(pkgRoot, "frontend_dist", "index.html"), "<html></html>")

	// Simulate a previously-staged older bundle, including a pgsql tool that's since been
	// removed from the package entirely.
	writeTestFile(t, postgresExePath(home), "old-pg-binary")
	writeTestFile(t, filepath.Join(dataDir(home), "pgsql", "bin", "removed-tool.exe"), "gone now")
	writeTestFile(t, pgsqlStagedBundleIDPath(home), "postgresql-16.14")
	writeTestFile(t, pythonExePath(home), "old-py-binary")
	writeTestFile(t, pythonStagedBundleIDPath(home), "3.14.0|abc123")

	if err := stageBundledFiles(pkgRoot, home); err != nil {
		t.Fatalf("stageBundledFiles failed: %v", err)
	}

	gotPg, err := os.ReadFile(postgresExePath(home))
	if err != nil {
		t.Fatal(err)
	}
	if string(gotPg) != "pg-binary" {
		t.Errorf("postgres.exe content = %q, want %q", string(gotPg), "pg-binary")
	}
	if _, err := os.Stat(filepath.Join(dataDir(home), "pgsql", "bin", "removed-tool.exe")); !os.IsNotExist(err) {
		t.Error("expected the pgsql tool removed from the new package to be gone")
	}
	gotPy, err := os.ReadFile(pythonExePath(home))
	if err != nil {
		t.Fatal(err)
	}
	if string(gotPy) != "py-binary" {
		t.Errorf("python.exe content = %q, want %q", string(gotPy), "py-binary")
	}
}

func TestStageBundledFiles_AlwaysRestagesFrontendDistEvenWhenAlreadyPresent(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()

	writePgsqlFixture(t, pkgRoot, "postgresql-16.14")
	writePythonFixture(t, pkgRoot, "3.14.0|abc123")
	writeBackendAppSourceFixtures(t, pkgRoot)
	writeTestFile(t, filepath.Join(pkgRoot, "frontend_dist", "index.html"), "<html>new build</html>")

	// Simulate a previous install's staged frontend_dist: an old index.html plus a stale,
	// content-hashed asset file that no longer exists in the new package at all (Vite renames
	// hashed filenames on every build) - reproduces the real issue #118 follow-up bug, where an
	// MSIX upgrade never re-copied frontend_dist because its marker (index.html) already existed.
	staged := frontendDistDir(home)
	writeTestFile(t, filepath.Join(staged, "index.html"), "<html>old build</html>")
	writeTestFile(t, filepath.Join(staged, "assets", "index-oldhash123.js"), "stale JS")

	if err := stageBundledFiles(pkgRoot, home); err != nil {
		t.Fatalf("stageBundledFiles failed: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(staged, "index.html"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "<html>new build</html>" {
		t.Errorf("expected frontend_dist to be re-staged with the new content, got %q", string(got))
	}
	if _, err := os.Stat(filepath.Join(staged, "assets", "index-oldhash123.js")); !os.IsNotExist(err) {
		t.Error("expected the stale content-hashed asset from the previous build to be removed")
	}
}

func TestStageBundledFiles_ErrorWhenFrontendDistCannotBeCleared(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()

	writePgsqlFixture(t, pkgRoot, "postgresql-16.14")
	writePythonFixture(t, pkgRoot, "3.14.0|abc123")
	writeBackendAppSourceFixtures(t, pkgRoot)
	writeTestFile(t, filepath.Join(pkgRoot, "frontend_dist", "index.html"), "<html></html>")

	lockDirectory(t, filepath.Join(frontendDistDir(home), "locked"))

	if err := stageBundledFiles(pkgRoot, home); err == nil {
		t.Error("expected an error when the existing frontend_dist cannot be cleared")
	}
}

func TestStageBundledFiles_ErrorWhenPgsqlSourceMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	// No pgsql/ under pkgRoot at all - not even a bundle-id.txt manifest.
	if err := stageBundledFiles(pkgRoot, home); err == nil {
		t.Error("expected an error when the source pgsql tree is missing")
	}
}

func TestStageBundledFiles_ErrorWhenPgsqlBundleIDMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	// pgsql/ has real content but no bundle-id.txt manifest - a malformed/broken package, distinct
	// from the payload being entirely absent above.
	writeTestFile(t, filepath.Join(pkgRoot, "pgsql", "bin", "postgres.exe"), "pg-binary")

	if err := stageBundledFiles(pkgRoot, home); err == nil {
		t.Error("expected an error when the package's pgsql bundle id is missing")
	}
}

func TestStageBundledFiles_ErrorWhenPythonSourceMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	// pgsql/ is present and stages successfully; python/ is missing under pkgRoot.
	writePgsqlFixture(t, pkgRoot, "postgresql-16.14")

	if err := stageBundledFiles(pkgRoot, home); err == nil {
		t.Error("expected an error when the source python tree is missing")
	}
	if _, err := os.Stat(postgresExePath(home)); err != nil {
		t.Errorf("expected pgsql to still have staged successfully before the python error: %v", err)
	}
}

func TestStageBundledFiles_ErrorWhenBackendAppSourceMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	// pgsql/ and python/ are present and stage successfully; python/app (the backend app
	// source stageBackendAppSource needs) is missing.
	writePgsqlFixture(t, pkgRoot, "postgresql-16.14")
	writePythonFixture(t, pkgRoot, "3.14.0|abc123")

	if err := stageBundledFiles(pkgRoot, home); err == nil {
		t.Error("expected an error when the source backend app tree is missing")
	}
	if _, err := os.Stat(pythonExePath(home)); err != nil {
		t.Errorf("expected python to still have staged successfully before the backend app source error: %v", err)
	}
}

func TestStageBundledFiles_ErrorWhenFrontendDistSourceMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	// pgsql/, python/, and the backend app source are present and stage successfully;
	// frontend_dist/ is missing.
	writePgsqlFixture(t, pkgRoot, "postgresql-16.14")
	writePythonFixture(t, pkgRoot, "3.14.0|abc123")
	writeBackendAppSourceFixtures(t, pkgRoot)

	if err := stageBundledFiles(pkgRoot, home); err == nil {
		t.Error("expected an error when the source frontend_dist tree is missing")
	}
	if _, err := os.Stat(pythonExePath(home)); err != nil {
		t.Errorf("expected python to still have staged successfully before the frontend_dist error: %v", err)
	}
	if _, err := os.Stat(filepath.Join(backendAppDir(home), "app", "main.py")); err != nil {
		t.Errorf("expected the backend app source to still have staged successfully before the frontend_dist error: %v", err)
	}
}

func TestStageBackendAppSource_StagesAppAndAlembic(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	writeBackendAppSourceFixtures(t, pkgRoot)

	if err := stageBackendAppSource(pkgRoot, home); err != nil {
		t.Fatalf("stageBackendAppSource failed: %v", err)
	}

	appDir := backendAppDir(home)
	for path, want := range map[string]string{
		filepath.Join(appDir, "app", "main.py"):                      "app-source",
		filepath.Join(appDir, "alembic", "versions", "0001_init.py"): "migration",
		filepath.Join(appDir, "alembic.ini"):                         "[alembic]",
	} {
		got, err := os.ReadFile(path)
		if err != nil {
			t.Errorf("expected %s to exist: %v", path, err)
			continue
		}
		if string(got) != want {
			t.Errorf("%s content = %q, want %q", path, string(got), want)
		}
	}
}

func TestStageBackendAppSource_AlwaysRestagesEvenWhenAlreadyPresent(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()

	writeTestFile(t, filepath.Join(pkgRoot, "python", "app", "main.py"), "new app source")
	writeTestFile(t, filepath.Join(pkgRoot, "python", "alembic", "versions", "0002_add_col.py"), "new migration")
	writeTestFile(t, filepath.Join(pkgRoot, "python", "alembic.ini"), "[alembic] new")

	// Simulate a previous install's staged app/alembic content, including a migration script
	// that's since been removed from the package entirely (e.g. squashed) - reproduces the same
	// class of bug already covered for frontend_dist's stale-asset test above, applied to #121.
	appDir := backendAppDir(home)
	writeTestFile(t, filepath.Join(appDir, "app", "main.py"), "old app source")
	writeTestFile(t, filepath.Join(appDir, "alembic", "versions", "0001_init.py"), "old migration")
	writeTestFile(t, filepath.Join(appDir, "alembic.ini"), "[alembic] old")

	if err := stageBackendAppSource(pkgRoot, home); err != nil {
		t.Fatalf("stageBackendAppSource failed: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(appDir, "app", "main.py"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "new app source" {
		t.Errorf("app/main.py content = %q, want %q", string(got), "new app source")
	}
	if _, err := os.Stat(filepath.Join(appDir, "alembic", "versions", "0001_init.py")); !os.IsNotExist(err) {
		t.Error("expected the removed migration script from the previous release to be gone")
	}
	got, err = os.ReadFile(filepath.Join(appDir, "alembic", "versions", "0002_add_col.py"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "new migration" {
		t.Errorf("alembic/versions/0002_add_col.py content = %q, want %q", string(got), "new migration")
	}
}

func TestStageBackendAppSource_ErrorWhenAppSourceMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	// No python/app under pkgRoot at all.
	if err := stageBackendAppSource(pkgRoot, home); err == nil {
		t.Error("expected an error when the source app tree is missing")
	}
}

func TestStageBackendAppSource_ErrorWhenAlembicSourceMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	writeTestFile(t, filepath.Join(pkgRoot, "python", "app", "main.py"), "app-source")
	// python/alembic is missing under pkgRoot.

	if err := stageBackendAppSource(pkgRoot, home); err == nil {
		t.Error("expected an error when the source alembic tree is missing")
	}
}

func TestStageBackendAppSource_ErrorWhenAlembicIniMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	writeTestFile(t, filepath.Join(pkgRoot, "python", "app", "main.py"), "app-source")
	writeTestFile(t, filepath.Join(pkgRoot, "python", "alembic", "versions", "0001_init.py"), "migration")
	// python/alembic.ini is missing under pkgRoot.

	if err := stageBackendAppSource(pkgRoot, home); err == nil {
		t.Error("expected an error when the source alembic.ini file is missing")
	}
}

func TestStageBackendAppSource_ErrorWhenAppDirCannotBeCleared(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	writeBackendAppSourceFixtures(t, pkgRoot)

	lockDirectory(t, filepath.Join(backendAppDir(home), "app", "locked"))

	if err := stageBackendAppSource(pkgRoot, home); err == nil {
		t.Error("expected an error when the existing app directory cannot be cleared")
	}
}

func TestStageBackendAppSource_ErrorWhenAlembicDirCannotBeCleared(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	writeBackendAppSourceFixtures(t, pkgRoot)

	lockDirectory(t, filepath.Join(backendAppDir(home), "alembic", "locked"))

	if err := stageBackendAppSource(pkgRoot, home); err == nil {
		t.Error("expected an error when the existing alembic directory cannot be cleared")
	}
}
