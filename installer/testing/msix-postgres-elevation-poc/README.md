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

**This CI run is deliberately a negative control on `windows-latest`, not the definitive
answer.** GitHub's own docs state `windows-latest` runners "are configured to run as
administrators with User Account Control (UAC) disabled" — one of PostgreSQL's own documented
admin-refusal trigger conditions. So a real personal-PC "normal non-elevated desktop session"
is exactly what this CI environment is not. The definitive positive-case test needs a real
Windows 11 machine with a normal local-admin account and default UAC — tracked as the Phase 2
follow-up once `installer/testing/`'s win11 VM is rebuilt (it doesn't currently exist on the
dev host that built this poc; recreating it needs a Windows 11 ISO and a manual GUI install
step, see `installer/testing/README.md`).

## Findings so far (Phase 1, 10 CI iterations on windows-latest)

Two genuine, unrelated-to-elevation problems were found and fixed along the way — both are
real findings worth keeping in mind for #65's actual architecture, not just poc debugging
noise:

1. **A full-trust MSIX package's own install directory blocks executing arbitrary bundled
   binaries in-place.** `Start-Process` on a bundled `initdb.exe`, run directly from
   `C:\Program Files\WindowsApps\<package>\...`, failed with **"Access is denied"** — a
   distinct OS/MSIX-level refusal, not PostgreSQL's own admin-permission message. Confirmed
   fix: copy the binaries into the package's own writable
   `%LocalAppData%\Packages\<PackageFamilyName>\LocalState\` folder first, then launch from
   there. This is a real constraint for #65's proposed architecture: **any bundled executable
   meant to actually run (not just be read) needs to be staged into a writable location before
   being launched, not executed in place from the package's install directory.**
2. **`postgres.exe`/`initdb.exe` need their full `bin` + `share` + `lib` sibling layout, not
   just `bin`.** Two iterations each caught one missing directory: first `share/postgres.bki`
   (initdb's own template data), then `$libdir/utf8_and_win` (one of PostgreSQL's built-in
   encoding-conversion shared libraries, which live in `lib/`, not `bin/` or `share/`) — both
   resolved via a path relative to the executable's own location. Purely a packaging
   completeness detail once known, but worth remembering: **stage `bin` + `share` + `lib`
   together, preserving their relative layout, for any future bundled-Postgres packaging.**

**No trace of PostgreSQL's own admin-refusal message was ever seen, across three separate runs
where the copy-and-launch mechanics worked and `initdb` genuinely ran** (not blocked by either
problem above) — despite `IS_ADMIN_ROLE=True` the entire time on this UAC-disabled runner,
exactly the condition documented to trigger the refusal. Each of those runs got measurably
further into initdb's real startup sequence (ownership message → locale/encoding detection →
checksums → the next missing-file error) without ever hitting an admin-permission complaint.
This is **not proof** the refusal can't happen (that check may fire very early, and a
still-outstanding packaging gap could be masking it, or something about the CI environment
could differ from a real check even while `IS_ADMIN_ROLE` matches) — but it's genuine,
non-trivial evidence leaning toward "no elevation problem here," gathered empirically rather
than assumed.

**Where iteration stopped (not a dead end, a deliberate pause):** the tenth run's bulk copy of
the full `pgsql` folder (bin+share+lib, ~120 MB, several hundred files including many small
`lib/*.dll`s) to LocalState hung past a 180-second deadline with no further progress logged —
plausibly Windows Defender's real-time protection scanning every file of a freshly-signed,
never-before-seen package as it's copied, though not confirmed. Since `windows-latest` was
never going to give the definitive elevation answer anyway (see above), this is where Phase 1
stops: the mechanics are proven (packaging, signing, sideload, AUMID launch, LocalState
read/write, the negative-control detection logic), and further GHA-specific copy-performance
debugging wouldn't change the real, still-open question — that needs Phase 2's real VM.

## How it works

`main.go` (packaged full-trust, `uap10:TrustLevel="mediumIL"`, launched via AUMID like the
loopback poc, no console) resolves its own package root and this package's writable
`%LocalAppData%\Packages\<PackageFamilyName>\LocalState\` folder — the only writable location
for a full-trust MSIX app, and also the only one guaranteed to resolve to the same physical
path from both inside the packaged app and the outside driving script (an earlier version used
`%TEMP%` for the result file specifically and it silently never appeared: `%TEMP%` sits under
`%LOCALAPPDATA%`, which MSIX's filesystem virtualization redirects for a running full-trust
package, so the two sides' view of the same literal path weren't the same physical file).

`main.go` then hands off to `worker_script.go`'s embedded PowerShell (invoked via `-File` on a
script written to LocalState, never `-Command` with inline substitution, so package paths
containing spaces need no manual escaping) — which measures
`[Security.Principal.WindowsPrincipal]::IsInRole(Administrator)` (a well-known one-liner
exactly mirroring the class of check `pgwin32_is_admin()` performs, not a hand-rolled Win32
token/SID syscall wrapper with no local Windows dev loop to iterate against), copies the
bundled `pgsql` folder into LocalState (see finding #1 above), then runs `initdb.exe` and
`pg_ctl.exe start` from there via `Start-Process -PassThru -Wait` with explicit
`-RedirectStandardOutput`/`-RedirectStandardError` (not `& $exe ... *> file`, which left exit
codes and output both silently empty in an earlier iteration) wrapped in `try`/`catch` (a bare
`Start-Process` throws rather than just returning a bad exit code when the target can't be
launched at all). The result — elevation state, exact exit codes, full stdout/stderr, and a
final verdict that greps stderr for PostgreSQL's own literal refusal string rather than
inferring anything from account state alone — is written back to the same LocalState folder
for the driving workflow to poll.

The bundled PostgreSQL is EDB's official portable "binaries only" Windows x64 zip
(`postgresql-16.14-1-windows-x64-binaries.zip` from `get.enterprisedb.com` — the same
distribution referenced in #65's own research, explicitly intended for embedding rather than
run through EDB's installer wizard). `pgsql/bin/`, `pgsql/share/`, and `pgsql/lib/` are staged
into the package (~120 MB) — `pgAdmin/`, `StackBuilder/`, `doc/`, and `include/` from the full
zip are dropped as unneeded at runtime, but the three staged directories' relative sibling
layout must be preserved (see finding #2 above).

## Re-running the verification

```
gh workflow run msix-postgres-elevation-poc.yml --repo lautou/pie-manager --ref <branch>
gh run watch --repo lautou/pie-manager
```

Re-run this if PostgreSQL's Windows admin-check, MSIX full-trust token/filesystem behavior, or
GitHub's `windows-latest` runner configuration ever changes in a way that might affect the
conclusion. For the definitive elevation answer (Phase 2), this needs to run — or be
reimplemented as a plain sideload script without CI at all — on a real Windows 11 machine with
a normal local-admin account, not `windows-latest`.
