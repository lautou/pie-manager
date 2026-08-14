# MSIX Postgres elevation proof-of-concept

Throwaway diagnostic build for [issue #76](https://github.com/lautou/pie-manager/issues/76) —
not part of the shipped product, never built or referenced by the real installer. Mirrors the
methodology already proven for issue #63's `msix-loopback-poc` (same manifest shape, same
ephemeral-cert packaging/sideload/AUMID-launch/result-file-poll/cleanup pattern) — see that
directory's own README for the shared mechanics; this one only documents what's different.

## Question it answers

Issue #65's native-Windows-port epic proposes bundling a portable PostgreSQL inside a full-trust
MSIX and running it as a plain, non-elevated child process — no Windows service, no elevation
prompt. PostgreSQL on Windows refuses to start under a user account whose process token has the
Administrators group SID "enabled" (`pgwin32_is_admin()` in `src/port/win32security.c`). Research
in #76 found this should NOT fire for a normal non-elevated process on an ordinary local-admin
account (UAC token-splitting marks that SID deny-only) — but this hadn't been confirmed
specifically inside a full-trust MSIX context.

**This particular run is deliberately a negative control, not the definitive answer** — see the
CI environment caveat below. The definitive positive-case test needs a real Windows 11 machine
with a normal local-admin account and default UAC (tracked as the follow-up once
`installer/testing/`'s win11 VM is rebuilt).

## Why this run is expected to fail — and why that's the correct, useful result here

GitHub's own docs state `windows-latest` runners "are configured to run as administrators with
User Account Control (UAC) disabled." That's one of PostgreSQL's own documented trigger
conditions for the admin-refusal (matching `pgwin32_is_admin()`'s check exactly, and confirmed by
an unrelated project, Scoop, independently observing the same "already admin" token on this
runner type — see #76's own research notes). So this run's job is to verify the **known-blocked**
case is correctly detected — not to prove the real target scenario (a normal non-elevated
desktop session) works. The result file's `VERDICT` line distinguishes:

- `EXPECTED_FAILURE` — blocked while `IS_ADMIN_ROLE=True`. This is the expected outcome on
  `windows-latest` and validates the test methodology is measuring the real thing.
- `UNEXPECTED_FAILURE` — blocked while `IS_ADMIN_ROLE=False`. Would mean something else broke
  (an MSIX path/permission issue, unrelated to elevation) — worth its own investigation.
- `SUCCESS` — postgres started even with `IS_ADMIN_ROLE=True`. Would contradict PostgreSQL's own
  documented behavior and be worth independently re-verifying before trusting it.

## How it works

`main.go` (packaged full-trust, `uap10:TrustLevel="mediumIL"`, launched via AUMID like the
loopback poc, no console) resolves its own package root and this package's writable
`%LocalAppData%\Packages\<PackageFamilyName>\LocalState\` folder (the only writable location for
a full-trust MSIX app — writing anywhere else, e.g. a literal `%LOCALAPPDATA%\...` path outside
that folder, gets silently redirected by MSIX's filesystem virtualization instead of erroring,
which would make the test's own file I/O unreliable, not just the admin check), then hands off
to `worker_script.go`'s embedded PowerShell — which measures
`[Security.Principal.WindowsPrincipal]::IsInRole(Administrator)` (a well-known one-liner exactly
mirroring the class of check `pgwin32_is_admin()` performs, not a hand-rolled Win32 token/SID
syscall wrapper with no local Windows dev loop to iterate against), then runs the bundled
`pgsql\bin\initdb.exe` and `pg_ctl.exe start` against a fresh data directory under that
`LocalState` folder. The result (elevation state, initdb/pg_ctl exit codes and output, final
verdict) is written to `%TEMP%\msix-postgres-elevation-poc-result.txt` for the driving workflow
to poll, exactly like the loopback poc's own result-file pattern.

The bundled PostgreSQL is EDB's official portable "binaries only" Windows x64 zip
(`postgresql-16.14-1-windows-x64-binaries.zip` from `get.enterprisedb.com` — the same
distribution referenced in #65's own research, explicitly intended for embedding rather than
run through EDB's installer wizard). Only `pgsql/bin/` and `pgsql/share/` are staged into the
package (~95 MB) — `pgAdmin/`, `StackBuilder/`, and docs from the full zip are dropped, since
`postgres.exe` locates its own `share/` directory via a path relative to `bin/`, so that
relative layout must be preserved but nothing else in the zip is needed.

## Re-running the verification

```
gh workflow run msix-postgres-elevation-poc.yml --repo lautou/pie-manager --ref <branch>
gh run watch --repo lautou/pie-manager
```

Re-run this if PostgreSQL's Windows admin-check, MSIX full-trust token/filesystem behavior, or
GitHub's `windows-latest` runner configuration ever changes in a way that might affect the
conclusion.
