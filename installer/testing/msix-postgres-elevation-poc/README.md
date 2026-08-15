# MSIX Postgres elevation proof-of-concept

Throwaway diagnostic build for [issue #76](https://github.com/lautou/pie-manager/issues/76) —
not part of the shipped product, never built or referenced by the real installer. Mirrors the
methodology already proven for issue #63's `msix-loopback-poc` (same manifest shape, same
ephemeral-cert packaging/sideload/AUMID-launch/result-file-poll/cleanup pattern) — see that
directory's own README for the shared mechanics; this one only documents what's different.

**Scope extended beyond #76's original question**: after confirming Postgres works, this poc
also bundles an embeddable Python + PgQueuer (the Celery/Redis replacement from #66) inside the
same package, to answer a natural follow-up — can the background-job side of #65's proposed
architecture be bundled too, not just the database? See "PgQueuer extension" below.

## Answer: YES — confirmed live on a real Windows 11 machine

**A bundled portable PostgreSQL starts and accepts real connections as a plain, non-elevated
child process launched from inside a full-trust MSIX package.** Confirmed on the project's own
`installer/testing/` win11 libvirt VM (real Windows 11, local account "pie", default UAC) — and
confirmed, via `Get-LocalGroupMember -SID S-1-5-32-544`, that "pie" is a genuine member of the
built-in Administrators group, not merely a standard/limited user. This is the exact scenario
issue #65 asked to verify ("a real Windows account that's a member of the Administrators group —
the common case for a personal PC"): the "refuses if Administrators-group member" check
`postgres.exe` performs is about group membership regardless of current elevation, so testing
against a plain non-privileged account would not have exercised the real concern at all.

- `IS_ADMIN_ROLE: False` for the packaged app's own process — UAC's token-splitting means an
  Administrators-group member's ordinary (non-elevated) processes still run at medium integrity,
  exactly like a full-trust MSIX app would. This is the real target scenario, not a proxy for it.
- `initdb` + `pg_ctl start` both succeeded (after fixing an unrelated missing-runtime problem,
  see Phase 2 below).
- Multiple live `postgres.exe` processes observed running (postmaster + the usual background
  workers), and a direct TCP connection to `127.0.0.1:5432` succeeded.
- No PostgreSQL admin-refusal message ever appeared, on this run or on any of the deeper Phase 1
  runs that got far enough to matter.

**Re-verified a second time with the fully Store-compatible fix in place**: the missing
Visual C++ Redistributable runtime is bundled *inside the package itself*
(`vcruntime140.dll`/`vcruntime140_1.dll`/`msvcp140.dll` copied into `pgsql/bin`, "app-local"
deployment — a Microsoft-documented redistribution method, not a workaround) instead of being
installed system-wide via `vc_redist.x64.exe`. On a VM reverted to a snapshot that had *never*
had the redistributable installed, confirmed by `Test-Path` before the test: the same
result — live `postgres.exe` processes, successful TCP connection to port 5432 — with **zero
external installer of any kind ever run**, matching the real target architecture exactly (no
elevation, no system-wide install, everything bundled in the MSIX).

This was the single most foundational open question for issue #65's native-Windows-port
epic — it's now empirically settled, not just researched. See Phase 2 below for the full
narrative, including two more real (non-elevation) problems this uncovered.

## PgQueuer extension — Answer: YES, also confirmed live

**An embeddable Python distribution + PgQueuer (the Celery/Redis replacement from #66) also
runs as a plain, non-elevated process from inside the same full-trust MSIX package, against the
bundled Postgres started above.** Confirmed on the same win11 VM, same Administrators-group
"pie" account (see the group-membership confirmation above):

- python.org's official "embeddable package" .zip (matching the real backend's exact Python
  3.14.0, with `pgqueuer==1.3.2`/`asyncpg==0.31.0` — the real backend's exact pins — pip-installed
  into it at CI build time) was bundled inside the package (~64 MB) and staged into LocalState
  the same way `pgsql/` is.
- `python -m pgqueuer install` created the real PgQueuer schema against the bundled, already
  non-elevated Postgres (`Installed PgQueuer schema (durability=durable).` — genuine PgQueuer
  output, not a canned test message).
- `python -m pgqueuer run <module>:main` started a real worker (`Async signal handlers are not
  supported on this platform; KeyboardInterrupt will still stop the worker.` — a genuine
  PgQueuer runtime warning, proof the actual library code executed, not just that the process
  launched) and registered a real cron schedule, confirmed independently via `psql -c "SELECT
  count(*) FROM pgqueuer_schedules WHERE entrypoint=...'"` returning exactly `1`.
- Both Postgres and the PgQueuer worker shut down cleanly on their own at the end of the test —
  no orphaned processes.

**Three real, non-elevation bugs were found and fixed reaching this result** — each is a general
Windows/PowerShell packaging lesson worth keeping in mind for #65's real architecture, not just
poc debugging noise:

1. **`Start-Process -Wait` hangs indefinitely when the target process spawns long-lived
   descendants that inherit its redirected output handles.** `pg_ctl start` spawns `postgres.exe`
   (plus its background workers), which inherit `pg_ctl`'s redirected stdout/stderr handles and
   keep them open for as long as postgres keeps running. `-Wait` uses .NET's parameterless
   `Process.WaitForExit()` internally, which waits for the redirected stream to reach EOF, not
   just for the process handle to signal — so it blocks forever while any handle-inheriting
   descendant is alive, even though the direct child (`pg_ctl.exe`) has already exited. Confirmed
   live via process inspection: `pg_ctl.exe` gone from `Get-Process` while `Start-Process` never
   returned, `postgres.exe` fully up. Fixed by using `-PassThru` and the *timed*
   `$proc.WaitForExit(ms)` overload instead, which only waits on the process handle. **Any
   Start-Process call whose target spawns a background daemon (not just queries one, as
   `pg_ctl status` would) needs this pattern, not the plain `-Wait` switch.**
2. **A .NET `Process` object obtained via `Start-Process -PassThru` doesn't always reliably
   expose `.ExitCode` after the timed `WaitForExit(ms)` overload**, even when it returns `true`
   and the process's own captured stdout clearly shows success. Worked around with a
   locale-independent fallback: `pg_ctl` only ever writes `postmaster.pid` on a genuinely
   successful start, so its presence overrides an unreadable exit code.
3. **`pip`'s generated console-script `.exe` launchers (`Scripts\pgq.exe`) can embed an absolute
   build-time interpreter path that breaks once the whole `python/` folder is relocated** — CI
   builds Python into a build-time path, but the poc must copy it into the package's LocalState
   folder at runtime (the same "install directory is read-only" constraint as `pgsql/`, see
   finding #1 in "Findings so far" below). Fixed by invoking `python.exe -m pgqueuer ...`
   directly instead of the generated launcher — [PgQueuer's own docs](https://pgqueuer.readthedocs.io/en/latest/cli.html)
   confirm this is fully equivalent, and it always resolves through the actual interpreter it's
   invoked with rather than a baked-in path.

Also worth noting, not a bug but an easy trap for a real port: **the real backend's PgQueuer
schema comes from Alembic migrations**, which this throwaway script has none of — `python -m
pgqueuer install` had to be called explicitly before `run`, or every `pgqueuer_*` table lookup
fails with "relation does not exist." A first pass at this test also had a **verification bug**
of its own: checking schedule registration with `-match "1"` false-matched the digit inside an
unrelated `LIGNE 1` (French "LINE 1") substring of that exact "relation does not exist" error,
making a real failure report as `PGQ_SCHEDULE_REGISTERED: True`. Fixed with an exact `-eq "1"`
match — a reminder that a poc's own verification logic needs the same scrutiny as the thing it's
testing.

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

## Phase 2 (definitive answer) — real Windows 11 VM

The project's own `installer/testing/` win11 libvirt/QEMU VM turned out to already exist (a
prior "it needs to be rebuilt" note in this file was based on checking `virsh list --all`
against the wrong libvirt connection — the domain was there all along under `qemu:///system`,
not `qemu:///session`). Workflow used: reverted the VM to its `base-clean-tuned-2026-07-17`
snapshot, started it, and drove everything through `qemu-guest-agent` (`virsh
qemu-agent-command`) — no SSH/RDP set up on this VM, and none needed.

**Getting the CI-built `poc.msix` onto the VM needed a different transfer than first tried.**
The workflow's artifact (`poc.msix` + `cert.cer`) was downloaded via `gh run download`. A first
attempt served them over HTTP from the host (`python3 -m http.server` bound to the libvirt
bridge IP) — `firewalld` on the host silently dropped the VM's inbound connection after the very
first byte range (one request got through, logged 200, then every retry failed to even
connect), and fixing that needed a `sudo` password not available non-interactively. Switched to
a completely network-free transfer instead: built a small ISO with `genisoimage` containing both
files, attached it to the *running* VM as its existing (already-empty) CD-ROM device via `virsh
change-media --insert ... --live`, then had the guest copy off of it — no firewall/network
dependency at all.

**`Add-AppxPackage` cannot run as the `SYSTEM` account.** `qemu-guest-agent`'s `guest-exec`
always runs as `SYSTEM` (it's a Windows service), and the very first sideload attempt failed
with HRESULT `0x80073CF9`: *"L'opération Add de déploiement a été rejetée... car le compte
Système local n'est pas autorisé à effectuer cette opération"* — AppX deployment operations are
scoped to a real interactive user session and explicitly reject `SYSTEM`, by design. Same
applies to `Get-AppxPackage` querying afterward (it only sees the *querying* user's own
per-user package graph — `SYSTEM` legitimately sees nothing, that's not a bug). Worked around
by creating a Scheduled Task with `/ru <user> /it` (run as that user, using their **existing
interactive token** — requires the user to already be logged in, confirmed via `(Get-CimInstance
Win32_ComputerSystem).UserName`), then `schtasks /run` to fire it immediately regardless of its
configured schedule. Every AppX-touching step (install, launch-and-poll) had to go through this;
plain file reads/writes (checking `result.txt`, stopping `pg_ctl`) didn't need it.

**One genuine environment gap, unrelated to elevation or MSIX:** the first real run got
`INITDB_EXIT: -1073741515` (`0xC0000135`, `STATUS_DLL_NOT_FOUND`) with completely empty
stdout/stderr — a Windows loader failure before `initdb.exe`'s own `main()` even runs. This
VM (a plain tuned Windows 11 install, unlike `windows-latest`'s dev-tool-loaded image) was
simply missing the Visual C++ Redistributable EDB's Postgres build links against
(`vcruntime140.dll`/`msvcp140.dll` confirmed absent via `Test-Path`). Fixed by downloading
Microsoft's official `https://aka.ms/vs/17/release/vc_redist.x64.exe` directly on the VM
(confirming real outbound internet access, independent of the earlier inbound-HTTP firewall
problem) and installing it silently (`/install /quiet /norestart`) — as `SYSTEM`, which is fine
for a normal elevated installer, just not for AppX operations specifically. **Any real
packaging of this architecture needs to bundle the VC++ Redistributable alongside PostgreSQL**,
not assume it's already present.

With both fixes in place, re-running the same launch script produced the result quoted at the
top of this document: `IS_ADMIN_ROLE: False`, live `postgres.exe` processes, a successful TCP
connection to port 5432. The very last cleanup steps inside the worker script (a `pg_ctl status`
+ `pg_ctl stop`) ran slowly enough on this VM's I/O that the outer 240-second polling deadline
elapsed before `result.txt` got its final `Set-Content` — not a failure, just confirmed directly
by checking for live `postgres.exe` processes and a real TCP connection instead of waiting
longer on the file. Postgres was then stopped cleanly via `pg_ctl stop`, and the VM was shut
down and reverted back to its `base-clean-tuned-2026-07-17` snapshot, leaving no trace.

### Second re-verification: app-local VC++ runtime, zero external installer

The first successful run above still relied on `vc_redist.x64.exe` having been run once on the
VM — not compatible with a real Store-distributable MSIX, which can't run an elevated external
installer at activation time. Re-verified with the actual fix: the CI workflow now installs the
redistributable once on the (disposable) runner purely to obtain
`vcruntime140.dll`/`vcruntime140_1.dll`/`msvcp140.dll`, then copies those 3 files into
`pgsql/bin` *inside the package* before signing — "app-local" deployment, a
Microsoft-documented redistribution method (Windows' DLL search order checks the executable's
own directory before any system path, so no installation step is needed by the end user or the
package at all).

Tested end-to-end on the VM reverted to the same clean snapshot, confirmed via `Test-Path` to
have never had the redistributable installed. Same result: live `postgres.exe` processes,
successful TCP connection to `127.0.0.1:5432` — this time with the redistributable never
touching the system at all, only ever existing inside the package. This is the fully
Store-compatible shape of the fix.

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
