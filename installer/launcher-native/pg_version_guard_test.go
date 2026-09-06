// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"os"
	"strings"
	"testing"
)

func TestParsePostgresVersionOutput(t *testing.T) {
	cases := []struct {
		name    string
		output  string
		want    int
		wantErr bool
	}{
		{"pg18", "postgres (PostgreSQL) 18.4\n", 18, false},
		{"pg16", "postgres (PostgreSQL) 16.14\n", 16, false},
		{"pg9x_style", "postgres (PostgreSQL) 9.6.24\n", 9, false},
		{"garbage", "not a version string\n", 0, true},
		{"empty", "", 0, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := parsePostgresVersionOutput(c.output)
			if c.wantErr {
				if err == nil {
					t.Fatalf("expected an error for %q, got major=%d", c.output, got)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != c.want {
				t.Errorf("got major=%d, want %d", got, c.want)
			}
		})
	}
}

func TestParsePgVersionFileContent(t *testing.T) {
	cases := []struct {
		name    string
		content string
		want    int
		wantErr bool
	}{
		{"plain", "18", 18, false},
		{"trailing_newline", "16\n", 16, false},
		{"trailing_whitespace", "  17  \n", 17, false},
		{"garbage", "not-a-number", 0, true},
		{"empty", "", 0, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := parsePgVersionFileContent(c.content)
			if c.wantErr {
				if err == nil {
					t.Fatalf("expected an error for %q, got major=%d", c.content, got)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != c.want {
				t.Errorf("got major=%d, want %d", got, c.want)
			}
		})
	}
}

func TestPostgresMajorMismatch(t *testing.T) {
	if postgresMajorMismatch(18, 16) != true {
		t.Error("expected a mismatch between 18 and 16")
	}
	if postgresMajorMismatch(18, 18) != false {
		t.Error("expected no mismatch between 18 and 18")
	}
}

func TestBundledPostgresMajorVersion_Success(t *testing.T) {
	home := t.TempDir()
	writeFakeExecutable(t, postgresExePath(home), `echo "postgres (PostgreSQL) 18.4"`)

	got, err := bundledPostgresMajorVersion(home)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != 18 {
		t.Errorf("got major=%d, want 18", got)
	}
}

func TestBundledPostgresMajorVersion_MissingExecutable(t *testing.T) {
	home := t.TempDir()
	if _, err := bundledPostgresMajorVersion(home); err == nil {
		t.Error("expected an error when postgres.exe does not exist")
	}
}

func TestBundledPostgresMajorVersion_UnparseableOutput(t *testing.T) {
	home := t.TempDir()
	writeFakeExecutable(t, postgresExePath(home), `echo "garbage"`)

	if _, err := bundledPostgresMajorVersion(home); err == nil {
		t.Error("expected an error when postgres.exe --version output can't be parsed")
	}
}

func TestExistingPgMajorVersion_Success(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(pgDataDir(home), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(pgVersionMarkerPath(home), []byte("16\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	got, err := existingPgMajorVersion(home)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != 16 {
		t.Errorf("got major=%d, want 16", got)
	}
}

func TestExistingPgMajorVersion_MissingFile(t *testing.T) {
	home := t.TempDir()
	if _, err := existingPgMajorVersion(home); err == nil {
		t.Error("expected an error when PG_VERSION does not exist")
	}
}

func TestCheckPostgresUpgradeCompatibility_FreshInstallIsNoop(t *testing.T) {
	home := t.TempDir()
	// isFirstRun(home) is true: no PG_VERSION file at all, no postgres.exe needed either.
	if err := checkPostgresUpgradeCompatibility(home); err != nil {
		t.Errorf("expected no error on a fresh install, got: %v", err)
	}
}

func TestCheckPostgresUpgradeCompatibility_SameVersionIsNoop(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(pgDataDir(home), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(pgVersionMarkerPath(home), []byte("18\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	writeFakeExecutable(t, postgresExePath(home), `echo "postgres (PostgreSQL) 18.4"`)

	if err := checkPostgresUpgradeCompatibility(home); err != nil {
		t.Errorf("expected no error when versions match, got: %v", err)
	}
}

func TestCheckPostgresUpgradeCompatibility_MismatchReturnsClearError(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(pgDataDir(home), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(pgVersionMarkerPath(home), []byte("16\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	writeFakeExecutable(t, postgresExePath(home), `echo "postgres (PostgreSQL) 18.4"`)

	err := checkPostgresUpgradeCompatibility(home)
	if err == nil {
		t.Fatal("expected an error on a version mismatch")
	}
	msg := err.Error()
	for _, want := range []string{"PostgreSQL 18", "PostgreSQL 16", pgDataDir(home)} {
		if !strings.Contains(msg, want) {
			t.Errorf("expected error message to mention %q, got: %s", want, msg)
		}
	}
}

func TestCheckPostgresUpgradeCompatibility_ErrorReadingExistingVersion(t *testing.T) {
	home := t.TempDir()
	// PG_VERSION exists as a directory instead of a file -> os.ReadFile fails.
	if err := os.MkdirAll(pgVersionMarkerPath(home), 0o755); err != nil {
		t.Fatal(err)
	}

	if err := checkPostgresUpgradeCompatibility(home); err == nil {
		t.Error("expected an error when PG_VERSION can't be read")
	}
}

func TestCheckPostgresUpgradeCompatibility_ErrorReadingBundledVersion(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(pgDataDir(home), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(pgVersionMarkerPath(home), []byte("16\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	// No postgres.exe staged at all -> bundledPostgresMajorVersion fails.

	if err := checkPostgresUpgradeCompatibility(home); err == nil {
		t.Error("expected an error when the bundled postgres.exe can't be queried")
	}
}
