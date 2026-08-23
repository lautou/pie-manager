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

func TestPgsqlStagedMarker(t *testing.T) {
	got := pgsqlStagedMarker(`C:\Users\pie`)
	want := postgresExePath(`C:\Users\pie`)
	if got != want {
		t.Errorf("pgsqlStagedMarker() = %q, want %q", got, want)
	}
}

func TestPythonStagedMarker(t *testing.T) {
	got := pythonStagedMarker(`C:\Users\pie`)
	want := pythonExePath(`C:\Users\pie`)
	if got != want {
		t.Errorf("pythonStagedMarker() = %q, want %q", got, want)
	}
}

func TestStageBundledFiles_CopiesAllThreeTreesOnFirstCall(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()

	writeTestFile(t, filepath.Join(pkgRoot, "pgsql", "bin", "postgres.exe"), "pg-binary")
	writeTestFile(t, filepath.Join(pkgRoot, "python", "python.exe"), "py-binary")
	writeTestFile(t, filepath.Join(pkgRoot, "frontend_dist", "index.html"), "<html></html>")

	if err := stageBundledFiles(pkgRoot, home); err != nil {
		t.Fatalf("stageBundledFiles failed: %v", err)
	}

	if _, err := os.Stat(pgsqlStagedMarker(home)); err != nil {
		t.Errorf("expected pgsql to be staged: %v", err)
	}
	if _, err := os.Stat(pythonStagedMarker(home)); err != nil {
		t.Errorf("expected python to be staged: %v", err)
	}
	if _, err := os.Stat(filepath.Join(frontendDistDir(home), "index.html")); err != nil {
		t.Errorf("expected frontend_dist to be staged: %v", err)
	}
}

func TestStageBundledFiles_SkipsAlreadyStagedPgsqlAndPython(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()

	writeTestFile(t, filepath.Join(pkgRoot, "pgsql", "bin", "postgres.exe"), "pg-binary")
	writeTestFile(t, filepath.Join(pkgRoot, "python", "python.exe"), "py-binary")
	writeTestFile(t, filepath.Join(pkgRoot, "frontend_dist", "index.html"), "<html></html>")

	// Pre-stage the pgsql/python markers directly, without a matching real source tree under
	// pkgRoot for either - if stageBundledFiles tried to copy them anyway, it would fail, so a
	// clean pass here proves the skip-if-present check fired for both.
	writeTestFile(t, pgsqlStagedMarker(home), "already-here")
	writeTestFile(t, pythonStagedMarker(home), "already-here")

	if err := stageBundledFiles(pkgRoot, home); err != nil {
		t.Fatalf("stageBundledFiles failed: %v", err)
	}

	got, err := os.ReadFile(pgsqlStagedMarker(home))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "already-here" {
		t.Errorf("expected the pre-staged pgsql marker content to survive untouched, got %q", string(got))
	}
}

func TestStageBundledFiles_AlwaysRestagesFrontendDistEvenWhenAlreadyPresent(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()

	writeTestFile(t, filepath.Join(pkgRoot, "pgsql", "bin", "postgres.exe"), "pg-binary")
	writeTestFile(t, filepath.Join(pkgRoot, "python", "python.exe"), "py-binary")
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

	writeTestFile(t, filepath.Join(pkgRoot, "pgsql", "bin", "postgres.exe"), "pg-binary")
	writeTestFile(t, filepath.Join(pkgRoot, "python", "python.exe"), "py-binary")
	writeTestFile(t, filepath.Join(pkgRoot, "frontend_dist", "index.html"), "<html></html>")

	// Make the existing staged frontend_dist un-removable: a subdirectory with its permission
	// bits stripped can't be traversed/deleted by os.RemoveAll. Restore permissions afterward
	// so t.TempDir()'s own cleanup can still remove it.
	locked := filepath.Join(frontendDistDir(home), "locked")
	writeTestFile(t, filepath.Join(locked, "file.txt"), "content")
	if err := os.Chmod(locked, 0); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(locked, 0o755) })

	if err := stageBundledFiles(pkgRoot, home); err == nil {
		t.Error("expected an error when the existing frontend_dist cannot be cleared")
	}
}

func TestStageBundledFiles_ErrorWhenPgsqlSourceMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	// No pgsql/ under pkgRoot at all.
	if err := stageBundledFiles(pkgRoot, home); err == nil {
		t.Error("expected an error when the source pgsql tree is missing")
	}
}

func TestStageBundledFiles_ErrorWhenPythonSourceMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	// pgsql/ is present and stages successfully; python/ is missing under pkgRoot.
	writeTestFile(t, filepath.Join(pkgRoot, "pgsql", "bin", "postgres.exe"), "pg-binary")

	if err := stageBundledFiles(pkgRoot, home); err == nil {
		t.Error("expected an error when the source python tree is missing")
	}
	if _, err := os.Stat(pgsqlStagedMarker(home)); err != nil {
		t.Errorf("expected pgsql to still have staged successfully before the python error: %v", err)
	}
}

func TestStageBundledFiles_ErrorWhenFrontendDistSourceMissing(t *testing.T) {
	pkgRoot := t.TempDir()
	home := t.TempDir()
	// pgsql/ and python/ are present and stage successfully; frontend_dist/ is missing.
	writeTestFile(t, filepath.Join(pkgRoot, "pgsql", "bin", "postgres.exe"), "pg-binary")
	writeTestFile(t, filepath.Join(pkgRoot, "python", "python.exe"), "py-binary")

	if err := stageBundledFiles(pkgRoot, home); err == nil {
		t.Error("expected an error when the source frontend_dist tree is missing")
	}
	if _, err := os.Stat(pythonStagedMarker(home)); err != nil {
		t.Errorf("expected python to still have staged successfully before the frontend_dist error: %v", err)
	}
}
