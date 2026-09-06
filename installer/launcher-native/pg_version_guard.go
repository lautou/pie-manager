// SPDX-License-Identifier: AGPL-3.0-or-later

package main

import (
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
)

// pgVersionOutputRe matches "postgres.exe --version"'s stdout, e.g.
// "postgres (PostgreSQL) 18.4\n" -> captures "18".
var pgVersionOutputRe = regexp.MustCompile(`PostgreSQL\)\s+(\d+)`)

// parsePostgresVersionOutput extracts the major version number from postgres.exe --version's
// raw stdout. Pure/testable — split out from bundledPostgresMajorVersion so the actual
// subprocess spawn doesn't need to be re-verified every time the parsing logic is exercised.
func parsePostgresVersionOutput(output string) (int, error) {
	m := pgVersionOutputRe.FindStringSubmatch(output)
	if m == nil {
		return 0, fmt.Errorf("could not parse a PostgreSQL major version out of: %q", strings.TrimSpace(output))
	}
	major, err := strconv.Atoi(m[1])
	if err != nil {
		return 0, fmt.Errorf("parsing major version %q: %w", m[1], err)
	}
	return major, nil
}

// bundledPostgresMajorVersion runs the bundled postgres.exe --version and returns its major
// version number. This is the actual source of truth for "what Postgres major version does
// this build of the app bundle" — deliberately not a hardcoded Go constant duplicating the
// version already pinned once in build-installer.yml's download URL, so a future major-version
// bump there can never silently drift out of sync with this check (the same reasoning behind
// installer/common.go's composePostgresMajor on the container-based installer, which parses the
// real compose file instead of hardcoding a second copy of the version).
func bundledPostgresMajorVersion(home string) (int, error) {
	out, err := exec.Command(postgresExePath(home), "--version").Output()
	if err != nil {
		return 0, fmt.Errorf("running postgres.exe --version: %w", err)
	}
	return parsePostgresVersionOutput(string(out))
}

// parsePgVersionFileContent extracts the major version number from a data directory's own
// PG_VERSION file content (PostgreSQL itself writes this file at initdb time — just the bare
// major version number, e.g. "16" or "18", with a trailing newline). Pure/testable.
func parsePgVersionFileContent(content string) (int, error) {
	trimmed := strings.TrimSpace(content)
	major, err := strconv.Atoi(trimmed)
	if err != nil {
		return 0, fmt.Errorf("parsing PG_VERSION content %q: %w", trimmed, err)
	}
	return major, nil
}

// existingPgMajorVersion reads the major version PostgreSQL was initialized with, from the
// on-disk data directory's own PG_VERSION file (see pgVersionMarkerPath). Only meaningful when
// !isFirstRun(home) — a fresh install has no such file yet.
func existingPgMajorVersion(home string) (int, error) {
	data, err := os.ReadFile(pgVersionMarkerPath(home))
	if err != nil {
		return 0, fmt.Errorf("reading %s: %w", pgVersionMarkerPath(home), err)
	}
	return parsePgVersionFileContent(string(data))
}

// postgresMajorMismatch is a pure comparison — split out purely for testability/naming
// symmetry with installer/common.go's own postgresMajorMismatch on the container-based
// installer, which this mirrors conceptually (same problem, no shared code possible: that one
// diffs an image tag against a podman volume's on-disk version, this one diffs a bundled
// binary's own --version output against this data directory's on-disk version).
func postgresMajorMismatch(bundled, existing int) bool {
	return bundled != existing
}

// checkPostgresUpgradeCompatibility guards against silently starting a newer bundled
// postgres.exe against an older on-disk data directory — PostgreSQL's on-disk format is not
// forward-compatible across major versions, and starting a mismatched postgres.exe against an
// existing pgdata risks real data corruption, not just a clean refusal (see
// backend/.claude/rules/containers-and-backup.md's "PostgreSQL major-version bumps" section for
// the general rule this launcher had no equivalent guard for before this fix — found live this
// session via a real user's cross-platform restore failure, see the root CLAUDE.md's
// launcher-native section for the incident).
//
// No-op on a genuinely fresh install (isFirstRun) — nothing to compare against yet, initdb
// creates a data directory matching the bundled version by construction.
func checkPostgresUpgradeCompatibility(home string) error {
	if isFirstRun(home) {
		return nil
	}

	existing, err := existingPgMajorVersion(home)
	if err != nil {
		return fmt.Errorf("could not determine the existing database's PostgreSQL version: %w", err)
	}

	bundled, err := bundledPostgresMajorVersion(home)
	if err != nil {
		return fmt.Errorf("could not determine the bundled PostgreSQL version: %w", err)
	}

	if postgresMajorMismatch(bundled, existing) {
		// Unlike the container-based installer's own equivalent guard (installer/common.go's
		// checkPostgresUpgradeCompatibility), this cannot tell the user to "reopen the old
		// version and take a backup first": the Microsoft Store silently replaces the previous
		// package on update, so by the time this guard ever fires there is no old-version binary
		// left to run — only the untouched PG%d data directory itself survives. The message
		// reflects that real constraint instead of pointing at a step that can't work here.
		return fmt.Errorf(
			"this update bundles PostgreSQL %d, but your existing data at %s was created with "+
				"PostgreSQL %d — incompatible on-disk formats, refusing to start against it to "+
				"avoid corrupting it. Nothing has been touched or deleted. Contact support with "+
				"this message to migrate that folder safely",
			bundled, pgDataDir(home), existing,
		)
	}
	return nil
}
