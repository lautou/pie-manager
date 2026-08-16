---
paths:
  - "installer/**"
  - "packaging/**"
  - ".github/workflows/build-installer.yml"
  - ".github/workflows/publish-images.yml"
  - "cliff.toml"
---

## Distribution

### Architecture: static Go installer

A single statically compiled binary (`CGO_ENABLED=0`), with no prerequisites.

```bash
# Install
curl -LO https://github.com/lautou/pie-manager/releases/latest/download/pie-manager-linux-amd64
chmod +x pie-manager-linux-amd64
./pie-manager-linux-amd64        # install (default subcommand)

# Launch (after install)
pie-manager start                 # or GNOME icon
```

| Subcommand | Role |
|---|---|
| `install` (default) | Pull quay.io images, write config files, create `.desktop`, start services |
| `start` | Read `.env` for port, start containers, open WebKitGTK window or browser |
| `version` | Print the installed version |

### Container images
- Published on **Quay.io** (`quay.io/ltourreau/pie-manager-*`) — **public**, no token required
- Images are version-tagged: `quay.io/ltourreau/pie-manager-backend:1.0.0` (pinned in `.env` via `APP_VERSION`)
- Build + push automated via `publish-images.yml` on tag `vX.X.X`

### Container image vulnerability scanning (Trivy)

`publish-images.yml` scans both published images with Trivy (`severity: HIGH,CRITICAL`) on every
release, with `ignore-unfixed: true` — Debian OS-package CVEs with no upstream fix are common and
not actionable (confirmed live: 103 such HIGH/CRITICAL findings on a single release, see #11/#18), so
filtering them out keeps the report limited to CVEs that can actually be fixed by bumping a
pinned version.

`msgpack`/`setuptools` (the two HIGH CVEs `requirements.txt` had no lever to fix — see #11) are
now structurally gone from the backend image via the multi-stage build in #20 (see the root
`CLAUDE.md`'s "Container architecture" section) rather than suppressed in the scan config.

**Still report-only for now** (`exit-code: 0` + `continue-on-error: true`) — see #21 to flip this
to a real release gate (`exit-code: 1`, drop `continue-on-error`) once the filtered scan has run
clean across a handful of releases, mirroring the `test-windows-install`/`test-linux-install`
progressive-hardening pattern below.

### Backend backup/restore smoke test (`smoke-test-backend`, #45)

`publish-images.yml`'s `smoke-test-backend` job (`needs: publish`, `continue-on-error: true` —
same progressive-hardening pattern as `test-windows-install`/`test-linux-install`) runs a real
`pg_dump`/`pg_restore` round-trip against the just-published backend image: starts a real
`postgres:16-alpine` GitHub Actions service, runs the image via
`podman run --network host` (so `localhost:5432` inside the container reaches the
service's host-published port) with the same `alembic upgrade head && uvicorn ...` command as
`compose-prod.yaml`, waits for `/api/admin/health`, seeds one portfolio, downloads
`/api/admin/backup`, re-uploads it to `/api/admin/restore`, then confirms the seeded portfolio is
still present. This exists because #20's multi-stage build hand-copies `pg_dump`/`pg_restore`'s
shared-library closure instead of apt-installing `postgresql-client`, and the Containerfile's own
build-time check (`pg_dump --version`) only proves the binaries *start* — it can't catch a future
base-image bump breaking the closure in a way that only surfaces against a real database. Verified
locally end-to-end (same commands, standalone containers) before landing.

### Dependabot + pinned base image digests

`.github/dependabot.yml` covers 6 ecosystems: `pip`/`npm`/`docker` (backend and frontend each),
`docker-compose` (root, covers both `compose.yaml` and `compose-prod.yaml`), and
`github-actions`. Every base image (`Containerfile` `FROM` lines, `compose.yaml`/
`compose-prod.yaml` `image:` lines) carries a `@sha256:` digest pin alongside its tag — without a
digest, Dependabot's `docker`/`docker-compose` ecosystems have nothing discrete to bump, and the
base image silently drifts underneath a floating tag (see #11/#19: a Trivy-flagged package was
already gone from a same-tag rebuild days later). If a Dependabot PR changes the tag itself (not
just refreshes the digest on the same tag), the "match CI's Python version" verification rule
above still applies — a passing CI job doesn't prove the Containerfile itself still builds.
`backend/Containerfile` has **two** `FROM` lines since its multi-stage refactor (#20, both
pinned to the same base+digest) — a Dependabot PR bumping one must bump both, or the
`builder` stage's `ldd`-computed shared-library closure ends up staged for a different glibc
than the `runtime` stage actually ships. `frontend/Containerfile` also has two `FROM` lines
since its own multi-stage refactor (#13) — same rule: bump both together.

### Windows executable code signing

`build-installer.yml` Authenticode-signs `launcher.exe` and `pie-manager-windows-amd64*.exe`
using a self-signed `CN=PIEManager` certificate (`osslsigncode`, since the whole workflow runs
on `ubuntu-latest` with no Windows runner — the Windows binaries are cross-compiled, not built
natively). Signing includes an RFC-3161 timestamp (`timestamp.digicert.com`), so the signature
stays valid after the certificate expires (2031). The PFX and its password live only as the
GitHub secrets `WINDOWS_CODESIGN_PFX_BASE64`/`WINDOWS_CODESIGN_PFX_PASSWORD` — a personal
backup of the PFX exists outside the repo/VM, not tracked here.

**This does not remove the Windows SmartScreen "Unknown Publisher" warning** — only a
CA-issued certificate with accumulated reputation does that. It provides a valid, verifiable,
non-expiring signature (integrity/authenticity), nothing more.

**Worse than SmartScreen: Smart App Control (SAC) can hard-block `launcher.exe` with no
override at all (issue #60).** Confirmed live on a fresh Windows 11 install (win11 test VM,
v1.3.3): after the installer completed successfully (all 6 containers healthy) and offered to
launch the app, Windows blocked `launcher.exe` outright ("Le Contrôle intelligent des
applications a bloqué une application potentiellement dangereuse") — unlike SmartScreen, this
dialog has no "Run anyway" option; the app simply never opens. Root cause confirmed via
registry (`HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState =
0x1`, i.e. SAC in full enforcement mode, not just the default post-install Evaluation state):
per Microsoft's own docs, SAC only accepts signatures chained to a CA in the Microsoft Trusted
Root Program — our self-signed cert doesn't qualify. **Notably, `pie-manager-windows-amd64.exe`
(the installer itself, signed with the same cert) was NOT blocked** — SAC classifies each
binary independently via cloud reputation first and only falls back to signature validity when
inconclusive, so this isn't fully deterministic from our side. SAC starts in "Evaluation" mode
on a fresh Win11 22H2+ install and can transition to full "On" on its own — exactly what
happened on this from-scratch VM, meaning any real user doing a truly fresh Windows install can
hit this wall with zero in-product workaround. **Confirmed this has no local-trust-store
workaround either**: the win11 test VM's `CN=PIEManager` cert is already present in both the
Root and TrustedPublisher stores (imported manually at some point, outside any setup script —
see caveat below) and SAC still blocked `launcher.exe` anyway, since SAC specifically requires
a chain to a CA in the Microsoft Trusted Root Program, not just local machine trust. See #60
for the full writeup — a real CA-issued cert is the only fully reliable fix; neither a
self-signed cert nor manually trusting it locally resolves this.

**The UAC prompt and the Firewall "allow this app" prompt read the publisher from two
different, unrelated places.** UAC shows "Éditeur vérifié: PIEManager" because it validates
the Authenticode signature — **caveat confirmed 2026-08-10 (see #60): the win11 test VM's
baseline snapshot (`base-clean-tuned-2026-07-17`) has the self-signed `CN=PIEManager` cert
pre-imported into Root/TrustedPublisher/`CurrentUser\My` (the last one with its full private
key, not just the public cert) — confirmed present on a virgin snapshot boot, before the
installer was ever run, so it predates any test session and was never part of the documented
`installer/testing/` setup scripts. A genuinely fresh Windows machine without that manual trust
step likely shows "Éditeur inconnu" instead** — this VM is not representative of a clean
install for UAC-publisher testing; re-verify on a real clean machine before trusting this
claim. The private-key-in-VM finding also means the PFX (not just the public cert) was
manually copied into this VM at some point, contradicting the "PFX lives only in GitHub
secrets + a personal backup outside the repo/VM" intent stated above — worth purging from a
future snapshot rebuild. The Firewall prompt shows "Éditeur: Inconnu" regardless of
signing, because it reads the `CompanyName`/`ProductName` fields from the binary's embedded
VERSIONINFO resource, separate from the manifest/icon. Fixed: `installer/winres/winres.json`
(go-winres, same tool/format as `installer/launcher/winres/winres.json`) regenerates
`installer/main_windows_amd64.syso` with those fields populated — regenerate via
`go run github.com/tc-hib/go-winres@latest make --in winres/winres.json --out main --arch amd64`
(the tool's default output naming, `main_windows_amd64.syso`, is exactly the file Go's build
expects — keep it, don't rename it to a bare `main.syso`). Avoid non-ASCII characters (em dash,
`—`) in any winres.json text field — one silently killed RT_VERSION generation entirely
(RT_MANIFEST still worked) with no error from the tool, confirmed by regenerating without it.

**Correction (2026-07):** the file was previously renamed to a bare `main.syso` in the mistaken
belief that Go wouldn't pick up the properly `_windows_amd64`-suffixed name — that belief was
never actually re-verified and turned out to be wrong. A bare, unsuffixed `.syso` has no
OS/ARCH scoping at all, so Go links it into **every** build target unconditionally, not just
Windows; this only surfaced as a real problem once a `darwin/arm64` build target was added
(`GOOS=darwin GOARCH=arm64 go build` failed with `unknown ARM64 relocation type 3`, since the
file is a Windows PE-COFF object). Verified empirically (byte-diffed the two resulting Windows
binaries, identical except Go's own build-ID cache string) that renaming back to
`main_windows_amd64.syso` produces the exact same signed Windows binary while fixing every
other platform. Never go back to a bare `main.syso`.

### MSIX/Microsoft Store distribution of launcher.exe alone — investigated and rejected (issue #63)

Issue #63 explored Store-distributing only `launcher.exe` as an MSIX package to route around
#60's Smart App Control (SAC) block (Store apps bypass SAC/SmartScreen by design), with the rest
of the app (WSL2/Podman/containers) staying a separately-elevated, sideloaded installer. Confirmed
live that a full-trust MSIX-packaged WebView2 control can reach `localhost` exactly like the
unpackaged exe (the loopback-isolation restriction only applies to sandboxed AppContainer/UWP
apps) — but **this specific shape of the approach** is a dead end, rejected twice by real
Microsoft Store certification on two separate policies:

- **10.2.5 Security** ("Installing and Updating Store Apps"): *"The product is primarily an
  installer for another app. Products distributed through the Store may only be installed
  through the Store."* — rejected an explicit "Install PIE Manager" button that downloaded and
  launched the real system installer (`pie-manager-windows-amd64.exe`) with a UAC elevation
  prompt triggered by that button click, not automatically on app launch.
- **10.1.5 Software Distribution**: *"The product promotes acquiring software outside the
  Store."* — rejected on content grounds, citing the button's own text.

A first, passive-message variant fared no better either (rejected under 10.1.2 Functionality:
*"fails to start with a message to download the App from outside the Store"*). There is no
in-between design that satisfies "the Store app must be fully functional on its own" while a
separately-elevated WSL2/Podman/container stack sits behind it — a single MSIX cannot mix an
elevated and non-elevated component, and Store certification is documented as very unlikely to
pass an app that forces elevation on launch.

**Not pursuing the paid-certificate path either** (SignPath Foundation, Azure Trusted Signing,
Sectigo/SSL.com — see #60): the realistic recurring cost (~$370-410/year) isn't justified for a
personal project, and even a paid cert must still build reputation with Microsoft's cloud
service before SAC reliably allows it through, so it wouldn't even be a guaranteed fix. SAC
checks whether a signature chains to a CA in the Microsoft Trusted Root Program — not whether
the signature is otherwise valid — so a self-signed certificate can never satisfy it either, no
matter how it's deployed or locally trusted.

**This does not mean no free fix exists — see issue #65/#82.** The rejections above specifically
targeted *downloading a separate installer at runtime + requesting elevation*, not Store
distribution itself. #65's own research (prompted by these exact rejections) found that an app
bundling **everything** it needs inside the MSIX package — no network download, no elevation, no
external installer, only ordinary non-elevated child processes — doesn't trigger either rejected
policy. #82 is the resulting native-Windows-port MVP (bundled Postgres + bundled Python backend,
no WSL2/Podman at all), now in active development. Until/unless that lands and passes
certification for real, the SAC block remains a known, accepted limitation whose only current
workaround is the end user disabling Smart App Control themselves (Settings → Privacy & security
→ Windows Security → App & browser control) — a real but drastic step, since re-enabling SAC
afterward requires reinstalling Windows.

**The Partner Center reservation from this investigation is still valid and reused by #82,
not recreated:** real identity `Name="PIEManager.PIEManager"`,
`Publisher="CN=2654AE3A-D473-41CE-8C17-0C2734C3B4A3"` (PFN
`PIEManager.PIEManager_9h5hzpm8nc7w0`, Store ID `9PM8GPSMJG0N`,
listing at https://apps.microsoft.com/detail/9PM8GPSMJG0N). Confirmed still present in the
Partner Center dashboard (2026-08-16), including a **privacy policy already drafted and on
file** that remains accurate for #82's architecture too (self-hosted, no data collected/
transmitted by the publisher, the only outbound network calls are public Yahoo Finance price
lookups, everything else stored locally) — no need to re-draft it. Category: Finances
personnelles > Banque + investissements. Support URL already set to the GitHub repo. A signing
certificate for local sideload testing must have a `Subject` matching this exact `Publisher` CN
(a real MSIX requirement, not just a trust nicety) — see `installer/launcher-native/
AppxManifest.xml` and `build-installer.yml`'s `package-native-launcher-msix` job for the real
packaging pipeline using this identity.

### Windows Firewall first-launch prompt (issue #82) — expected, not a bug to fix

On a fresh install, first launch shows a "Windows Security Alert" dialog ("Voulez-vous
autoriser les réseaux publics et privés à accéder à cette application ?") for the bundled
`postgres.exe`/`python.exe` (uvicorn) — both bind `127.0.0.1` only, yet the prompt still
appears. **"Loopback binds are exempt from this prompt" is folklore, not fact** — confirmed
against Microsoft's own Windows Firewall docs: the interactive notification fires on *any*
new, unrecognized executable path calling `listen()`, with no bind-address qualifier at all.
The genuinely-real loopback exemption is a separate mechanism (WFP's loopback packet
classification) that governs whether *traffic* passes the resulting rule, not whether the
*dialog* appears — which is exactly why the app is fully functional (health checks, log
files) whether or not anyone ever dismisses the dialog, confirmed live in CI where nothing is
present to click it.

**No elevation-free fix exists.** Both `netsh advfirewall`/Group Policy pre-provisioning and
the `INetFwPolicy2`/`INetFwRule` COM API are admin-gated for inbound rules with no per-user
exception — confirmed directly against Microsoft's docs, which state plainly that a
non-admin's response to the dialog only ever creates a *block* rule regardless of which
option is clicked, and that the whole automatic-rule-creation mechanism "require[s] user
interaction and administrative privilege." Adding a rule from this app's own first-run code
would either silently fail (standard user) or trigger the exact UAC-style elevation prompt
this app's whole design exists to avoid (see the #63 section above) — not an acceptable
trade to suppress a cosmetic dialog. A structural workaround (Unix-domain sockets instead of
TCP loopback) is also a dead end: `asyncpg` explicitly refuses Unix sockets on Windows
regardless of OS/Postgres support, and even if it worked for Postgres, uvicorn still needs a
real TCP listener for WebView2's `Navigate()` call — browsers don't navigate to Unix sockets
without a custom scheme handler, a much bigger redesign for zero net benefit (it would still
leave uvicorn's own listener triggering the same prompt).

**Decision: accept it as a one-time, first-run UX cost**, matching every comparable
bundled-local-server desktop app (XAMPP, local dev-server tooling, etc.) — this is
industry-standard friction, not a PIE Manager-specific defect. One meaningfully good property
worth noting: unlike WebView2's own well-documented "prompts on every update" problem (caused
by its Evergreen runtime's version-numbered install path — see WebView2Feedback #2252/#3604),
this app's bundled `postgres.exe`/`python.exe` sit at stable, non-versioned paths
(`%USERPROFILE%\PieManager\pgsql\bin\postgres.exe`, `...\python\python.exe` — see
`paths.go`), and Windows Firewall rules are keyed on full executable path with no wildcard
support — so this should be a true one-time-per-machine event on first install, not a
recurring one on every app update. `main.go`'s `loadingHTMLTpl` (the WebView2 loading screen
shown while `startupSequence` runs) includes a one-line hint that this is expected and safe
to dismiss either way, so a real user isn't left wondering if something's wrong.

### Installed files (Linux)
```
~/.local/share/pie-manager/   compose-prod.yaml, haproxy.cfg, .env, pie-manager (binary), VERSION
~/.local/share/pie-manager/   wrapper.py (only if WebKitGTK is available)
~/.local/share/applications/  pie-manager.desktop
~/.local/share/icons/hicolor/ pie-manager.svg + .png
~/.local/bin/                 pie-manager (symlink)
```

### Installed files (Windows)
```
%APPDATA%\pie-manager\   compose-prod.yaml, haproxy.cfg, .env, VERSION
%APPDATA%\pie-manager\   launcher.exe, start-podman.vbs
Start Menu\Programs\     PIE Manager.lnk  (→ launcher.exe)
```

### Installed files (macOS)
```
~/Library/Application Support/PieManager/   compose-prod.yaml, haproxy.cfg, .env, pie-manager (binary), VERSION
~/Library/LaunchAgents/                     com.pie-manager.podman-start.plist
~/Applications/                             PIE Manager.app  (Contents/MacOS/pie-manager-launcher)
~/.local/bin/                               pie-manager (symlink)
```

### Windows installation architecture

On Windows, PIE Manager requires WSL2 + Podman Machine (a WSL2-backed Fedora CoreOS VM)
+ Docker Compose (installed via winget). The installer (`pie-manager-windows-amd64.exe`) is a
single statically compiled Go binary that handles the full setup.

**Compose provider:** `docker-compose.exe` (installed on the Windows host via winget). HAProxy
and all containers communicate over Podman's internal Docker-compatible network.

**Launcher:** `launcher.exe` is a native Go binary using WebView2 (pre-installed on Windows 11).
It replaces the old `launcher.ps1`/`open-app.vbs`/Edge `--app` chain. It:
- Shows the PIE Manager icon in the Windows taskbar (AUMI belongs to our .exe)
- Detects if a window is already open (single-instance via FindWindowW)
- Shows a native loading screen while polling `/api/admin/version`
- Navigates to the app in a WebView2 window once the backend is ready

**Window title bar icon** requires an explicit `IconId` — `jchv/go-webview2`'s `webview2.New()`
falls back to the generic Win32 stock icon (`IDI_APPLICATION`) whenever `WindowOptions.IconId`
is left at zero; it does not automatically pick up the exe's own embedded icon resource, even
though one is present via `winres/winres.json`. Fix: key the icon group by numeric ID in
`winres.json` (`"RT_GROUP_ICON": {"#1": {...}}`, not a string name like `"APP"` — the API only
accepts a numeric resource ID), then construct with
`webview2.NewWithOptions(webview2.WebViewOptions{WindowOptions: webview2.WindowOptions{IconId: 1}})`
instead of `webview2.New(false)`.

**Auto-start:** A Windows Task Scheduler task runs `start-podman.vbs` at login (wscript.exe,
completely invisible). This starts the Podman Machine. Containers restart automatically via
`podman-restart.service` inside the Fedora CoreOS VM.

**VmmemWSL memory:** ~3-4 GB is normal — the Podman Machine VM + all containers.

**Windows install sequence (fresh machine):**
1. Run `.exe` as Administrator → installs WSL2, Podman CLI, Docker Compose (may reboot)
2. After reboot, installer auto-resumes via a Windows Scheduled Task (not RunOnce — see
   "Auto-resume after reboot uses a single Scheduled Task" below)
3. `podman machine init` + start (~650 MB download)
4. All 6 containers pulled and started via `podman compose up -d`
5. `launcher.exe` deployed, Start Menu shortcut created, Task Scheduler registered

The `.env` file written by the installer contains:
```
APP_VERSION=<version>
INSTALLER_VERSION=<version>
APP_PORT=<port>
```

### Windows gotchas (do not repeat these mistakes)

**Store-independent WSL2/winget install** — `wsl --install --no-distribution` fetches the
actual WSL2 engine as a Microsoft Store app, and `winget` itself is normally provisioned
through the Store too; both are silently absent on a fresh **local-account** Windows install
(Store provisioning never triggers without a Microsoft-account first login) — confirmed live
in a test VM. `main_windows.go` now enables the two required optional features directly via
DISM (`enableWindowsFeature`, bypassing `wsl --install`'s own flaky attempt at this), and
falls back to downloading the official `.msixbundle` packages straight from
[microsoft/WSL](https://github.com/microsoft/WSL/releases) and
[microsoft/winget-cli](https://github.com/microsoft/winget-cli/releases) releases
(`installWSLFromGitHub`/`installWingetFromGitHub`) when the Store-dependent path fails —
Microsoft's own documented offline/enterprise install method, not a hack.

**WSL2 readiness must check the actual engine, not just DISM feature flags.** `isWSL2Ready()`
used to check only whether `Microsoft-Windows-Subsystem-Linux`/`VirtualMachinePlatform`
report `State=Enabled`. Confirmed live: both can report `Enabled` (with `RestartNeeded=False`,
so not a pending-reboot issue either) while the WSL kernel/engine was never installed — e.g.
the features were toggled independently, or an earlier run enabled them via DISM but was
interrupted before `wsl --install` finished. The installer then logged "WSL2 déjà installé"
and skipped straight to Podman machine init, which failed with a confusing "WSL isn't
installed" error. Fixed: `isWSL2Ready()` now runs `wsl --status` directly — it exercises the
real engine and requires both features anyway, so it's a single, reliable signal instead of
two flags that can drift from actual system state.

**Cosmetic: `wsl.exe`'s own console chatter and the WSL Settings "welcome" popup are both
suppressed, not just tolerated.** `wsl --install`'s stdout/stderr is now captured
(`CombinedOutput()`), not streamed to the console — it prints confusing internal diagnostics
(e.g. "not installed, run wsl --install" as part of its own self-check) that read as a real
error; the raw text is still logged, replaced on screen with our own curated status lines.
Separately, the WSL Settings onboarding window (`wslsettings.exe`, launched by `wslservice.exe`
via `----ms-protocol:wsl-settings://oobe`) used to pop up mid-install — confirmed via
microsoft/WSL's own source (`LxssUserSession.cpp`'s `_LaunchOOBEIfNeeded`) that it fires the
first time ANY WSL distro is registered on the machine, including Podman Machine's own
`podman-machine-default` distro — nothing specific to our WSL2 install step. Its entire gate is
one registry DWORD, `HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss\OOBEComplete` — the
exact value `wslservice.exe` itself writes after a real OOBE run. `disableWSLOOBEWelcome()` sets
it preemptively, early in `main()`, doing ahead of time what the OS does reactively.

`Add-AppxPackage` itself is confirmed live (real elevated non-SYSTEM user, test VM) to work
correctly for VCLibs/UI.Xaml/winget. The one real failure mode hit live is HRESULT
`0x80073D06` ("a higher version of this package is already installed") — some Windows 11
builds ship a newer in-box framework package than the version this installer pins, and AppX
dependency resolution only requires "at least this version," so it's harmless. `addAppxPackage`
treats this specific HRESULT as success (`isAppxAlreadyNewerError` in `common.go`).

**`podman-restart.service` enable via SSH** — `systemctl --user enable` fails silently when
`~/.config/systemd/user/default.target.wants/` is owned by root (Podman Machine default).
Fix: create the symlink directly after fixing ownership, chaining the steps with `&&`.

**`podman machine ssh` mangles a compound `&&`-chained command passed as `"bash", "-c",
cmd`** — confirmed live and matches an independent upstream report
([containers/podman#13517](https://github.com/containers/podman/issues/13517)): it re-joins
multiple trailing arguments before forwarding them over SSH, so `bash`, `-c`, and the command
string arrive at the remote shell re-split on whitespace — only the first word after `-c`
survives as its actual script argument (observed live as a bare `sudo` invocation dumping its
usage text, silently no-op'ing the whole setup step). Fix: pass the full compound command as
the **sole** trailing argument after `--`, no separate `"bash", "-c"` — the remote SSH server
already wraps a single command string in a shell itself.

**Podman machine start at login** — the Task Scheduler VBS uses `True` (wait) + retry loop
(up to 5 attempts, 5s between) because WSL2 may not be ready immediately at login.

**Auto-resume after reboot uses a single Scheduled Task, not RunOnce — do not add RunOnce
back.** An earlier version registered both a `HKCU\...\RunOnce` entry AND a Scheduled Task
(`RunLevel Highest`, `-AtLogOn -User $env:USERNAME`) as redundant auto-resume mechanisms,
since RunOnce alone was intermittent on at least one test VM: a failed-to-fire RunOnce entry
survives completely **unconsumed** in the registry (Windows always deletes a RunOnce value
immediately before running it, success or failure, so a surviving value means it was never
attempted that boot at all — a documented class of quirk with RunOnce pointing at a
`requireAdministrator`-manifested executable). The Scheduled Task backup was added to cover
that flakiness. **This redundancy was then confirmed live to actively cause the worse bug it
was meant to guard against**: both mechanisms fired for the same logon, and — critically —
each one triggers its own elevation event *before* any of our code (including a
`CreateMutexW`-based single-instance lock, `acquireSingleInstanceLock` in
`main_windows.go`) ever runs, since Windows decides whether to elevate before the process
image executes. Confirmed live as one silent auto-elevation plus one visible UAC consent
dialog for the same logon — a mutex can only stop the *second* instance from doing duplicate
work once both have already elevated, it cannot suppress the extra prompt itself. The only
fix that actually prevents the double elevation event is registering a single mechanism.
RunOnce was dropped; the Scheduled Task was kept, since it is Microsoft's documented
mechanism for reliably resuming an elevated process at logon and doesn't share RunOnce's
silent-no-fire quirk. The single-instance mutex is kept anyway as a general defensive guard
(e.g. a manual double-launch of the resumed installer), just no longer covering this specific
race. Since the installer's own SKIP-logic makes every step idempotent regardless, a manual
re-launch of the `.exe` after reboot remains a safe fallback if the Scheduled Task ever fails
to fire.

**RESOLVED — the "intermittent" final popup was never failing to render, it was rendering
BEHIND the console window.** A `MessageBox.Show(msg, title, ...)` call with no owner window
has no z-order relationship to the installer's own console window — Windows is free to leave
it behind the (still-focused) console, silently, with no error. Confirmed live via screenshot:
the popup was present and fully functional, just hidden under the console the whole time.
Fixed by giving every popup an invisible, `TopMost`-set owner `Form` (`topmostOwnerPS` in
`main_windows.go`, prepended to both `popup()`'s and `popupYesNo()`'s script) — an owned
window is kept above its owner in z-order, and a `TopMost` owner keeps it above unrelated
windows too. Accessing `$owner` in `MessageBox.Show($owner, ...)` is what forces the form's
native handle into existence even though `.Show()` is never called on it — no visible extra
window appears.

**Final popup asks Yes/No to launch immediately, and both a Desktop and Start Menu shortcut
are created** — `popupYesNo()` (mirrors `popup()`, `MessageBoxButtons.YesNo` +
`MessageBoxIcon.Question`, matches on the literal `"Yes"` return string). Answering "Oui"
starts `launcher.exe` directly (fire-and-forget `exec.Command(...).Start()`, not `.Run()` —
it's a long-lived GUI process the installer must not wait on). The desktop shortcut resolves
its path via PowerShell's `[Environment]::GetFolderPath('Desktop')`, not a hardcoded
`%USERPROFILE%\Desktop`, since that breaks under Known Folder Move (OneDrive-redirected
Desktop). Before this, only a Start Menu shortcut was actually created despite the
surrounding log/comment text already claiming "desktop shortcut" — a real, silent gap now
fixed, not a rename.

### Native window integration (wrapper.py / WebKitGTK) — Linux only

At install time, `deployWrapper()` checks whether Python 3 + WebKitGTK 2 (`gi`, `WebKit2 4.1`)
are available. If yes, it writes `wrapper.py` to the install directory.

`openBrowser()` in `start.go` prefers `wrapper.py` (native WebKitGTK window, no browser chrome)
over Epiphany application mode, then falls back to the default browser via `xdg-open`.

`wrapper.py` behavior:
- Opens a GTK window sized 1400 × 900.
- If the backend already responds on first launch, navigates directly to the app.
- Otherwise shows an **animated loading screen** (dark background, progress bar) and polls
  `GET /api/admin/version` every 600 ms; navigates once the backend is ready.
- Intercepts navigation: external URLs are blocked, non-HTML responses trigger a file download
  (used for the database backup endpoint).

`focusExistingWindow()` in `start.go` prevents opening a second window when the user clicks
the GNOME icon while the app is already running. On Linux it tries `wmctrl`, then `xdotool`,
then falls back to checking whether `wrapper.py` is in the process list via `pgrep`.

The desktop entry (`Exec=<install-dir>/pie-manager start`) always invokes `pie-manager start`,
which handles the case where containers have stopped after a reboot.

## macOS installation architecture

**Apple Silicon (arm64) only — no Intel/amd64 build.** Apple Silicon is now the dominant Mac
architecture and the only one with a future: macOS 27 "Golden Gate" (Sept 2026) drops Intel
support entirely, and GitHub's own `macos-latest` Actions runner already defaults to arm64.
Building an amd64 binary too would cost nothing at compile time (Go cross-compiles both from
the same source) but there is no way to *test* it — see below — so it's simply not built.

**Target macOS version: 14 Sonoma minimum, 15 Sequoia recommended.** The installer doesn't
pass a `--provider` flag to `podman machine init`, so it relies on whatever Podman's own
current default is for macOS — **`libkrun`, not `applehv`** (verified against
docs.podman.io: `libkrun` is the starred/default provider for macOS in current Podman
releases; `applehv` is only the alternative — correcting an earlier wrong claim in this
file). Either provider requires macOS 13 Ventura at minimum — but Ventura is already EOL (no
security patches since Aug 2025), so Sonoma (still patched) is the documented floor instead.
No runtime OS-version check exists in
the installer itself; like Linux/Windows, it lets Podman fail with its own error on an
unsupported OS.

**No local test VM — testing happens exclusively on GitHub Actions' real Apple Silicon
runners (`macos-26`).** Unlike Windows (tested via a local libvirt/QEMU VM, see
`installer/testing/`), Apple Silicon macOS **cannot be virtualized on x86_64 hardware by any
known method** — KVM only accelerates matching host/guest architectures, and arm64 macOS is
hardware-locked to Apple Silicon SoC features (Secure Enclave, custom boot chain) with no
non-Apple equivalent. The OSX-KVM/Hackintosh community tooling only ever supports x86_64
macOS on x86_64 hosts, which is irrelevant now that amd64 is out of scope. `test-macos` in
`build-installer.yml` runs the release smoke test on genuine Apple Silicon hardware instead —
arguably better coverage than a VM would give anyway.

**No code signing or notarization — the binary is unsigned, exactly like the Windows
SmartScreen situation.** Real macOS code signing + notarization requires a paid Apple
Developer Program account ($99/year), which this project doesn't have. macOS Gatekeeper
blocks first launch of an unsigned/unnotarized binary ("cannot be opened" / "is damaged") —
the documented fix is `xattr -d com.apple.quarantine <binary>` (the GUI right-click bypass
does not apply to a plain CLI binary, and became unreliable on macOS Tahoe anyway). No
`osslsigncode`-equivalent tool exists for Apple's signing format, so unlike Windows there's
nothing to automate here — see README's "Sécurité et signature de code" for the user-facing
framing.

**Podman itself is auto-installed via its own official `.pkg`, not Homebrew.** Homebrew was
considered and rejected as the bootstrap mechanism: installing Homebrew itself requires Xcode
Command Line Tools, whose install pops up an interactive GUI dialog with no reliable silent
mode — unlike Windows's winget/DISM, which are fully scriptable. Instead,
`installPodmanFromGitHub()` in `install_darwin.go` reuses the exact same "official package
straight from GitHub, not a third-party package manager" pattern already used for WSL2/winget
on Windows (`githubLatestAssetURL`/`downloadFile` from `common.go`): downloads
`podman-installer-macos-arm64.pkg` from `containers/podman`'s latest release, then
`sudo installer -pkg ... -target /` (macOS's native package-install CLI, no GUI). Podman's own
docs recommend this `.pkg` over Homebrew anyway ("community-maintained, we cannot guarantee
stability"). `sudo`'s password prompt reads from the installer's own `Stdin`/`Stdout`/`Stderr`
(connected through, not discarded) since it's expected to run interactively from a Terminal —
exactly like Linux's `dnf install` message assumes a Terminal, just one step more automated.
Only handles a **fresh** install (`podman` absent from PATH) — re-running the `.pkg` to
*upgrade* an already-installed Podman is a documented fragile path upstream
(`podman-mac-helper` conflicts, requires manually uninstalling the old helper first), so
upgrades are left to the user/Homebrew, not this installer.

**Right after a fresh `.pkg` install, `podman` is still not on `PATH` for the current
process.** The `.pkg` registers its install directory via `/etc/paths.d/` for *future login
shells* only — confirmed live in CI: `podman machine init` failed with "executable file not
found in $PATH" immediately after "The install was successful." `refreshPathForPodman()`
reads that same `/etc/paths.d/` entry and prepends it to the current process's `PATH` before
continuing, rather than hardcoding the `.pkg`'s install directory. Also,
`githubLatestAssetURL` (`common.go`, used here and by Windows's WSL2/winget fallback) now
passes `GITHUB_TOKEN`/`GH_TOKEN` as a bearer token when present in the environment — shared
GitHub Actions runner IPs can already be near the unauthenticated GitHub API's 60/hour limit
(confirmed live: a real 403), while a real end user's install never has this env var set.

**Podman Machine setup itself does port over from Windows, since Podman Machine's own guest
OS (Fedora CoreOS) is identical on both platforms.** `ensurePodmanMachine()` in
`install_darwin.go`/`start_darwin.go` mirrors Windows's init/start logic (`podman machine
list --format json`, parse `Running`), and `configurePodmanRestartService()` reuses the exact
same `podman machine ssh` compound-command pattern as Windows (see Windows gotchas above for
why the whole `&&`-chained command must be the sole trailing argument, never split as
separate `"bash","-c",cmd` arguments — the same footgun applies identically here).

**Auto-start at login uses a `launchd` LaunchAgent, not Task Scheduler.**
`~/Library/LaunchAgents/com.pie-manager.podman-start.plist` (`RunAtLoad`) runs `podman machine
start` at login — the direct functional equivalent of Windows's Scheduled Task +
`start-podman.vbs`, loaded/unloaded via `launchctl load`/`unload`.

**No native WebView launcher for v1 — `open <url>` (default browser), matching Linux's own
fallback path.** Windows's `launcher.exe` uses `go-webview2`, a cgo-free binding to the
pre-installed WebView2 runtime. No equivalent cgo-free WebKit binding exists for Go on macOS;
the community `webview/webview` binding needs cgo, which would break `CGO_ENABLED=0`
cross-compilation from Linux CI (cgo cross-compiling to Darwin needs a macOS SDK/clang
cross-toolchain, not just `GOOS`/`GOARCH` env vars). Revisit only if a native window shell is
specifically wanted later — `open <url>` is a legitimate, low-maintenance v1 experience.

**The `/Applications` shortcut is a minimal hand-built `.app` bundle, not a compiled GUI.**
`installAppBundle()` writes `~/Applications/PIE Manager.app/Contents/{Info.plist,MacOS/
pie-manager-launcher}` — a static `Info.plist` (embedded from `packaging/
pie-manager-macos-info.plist`, `__VERSION__` substituted at install time, same pattern as
Linux's `.desktop` `Exec=` substitution) plus a one-line shell script that just runs
`pie-manager start`. No compiled Swift/ObjC, no icon (no `.icns` — Finder shows the generic
app icon; skipped to avoid needing macOS-only icon-conversion tooling `iconutil` in a
Linux-only CI pipeline), no code signing needed for it to be double-clickable. `LSUIElement:
true` in the plist intentionally suppresses the Dock bounce/menu bar flash, since the bundle's
process is fire-and-forget (starts services, opens the browser, exits) rather than a
persistent app with a window.

**Install location:** `~/Library/Application Support/PieManager` — macOS's own idiomatic
per-user app-data convention, playing the same role as Linux's `~/.local/share/pie-manager`.

**Shared refactor enabling this:** `readInstalledVersion`, `detectComposeCmd`,
`podmanImageExists`, `updateEnvPort`, `forceRecreate`, and `copyFile` were moved from
`install.go`/`start.go` (previously `//go:build linux`-scoped) into `common.go` (no build
tag) — these six functions are pure `os`/`os/exec`/`path/filepath` calls with no Linux-specific
behavior, so `install_darwin.go`/`start_darwin.go` reuse them directly instead of duplicating
them, the same way `main_windows.go` does *not* reuse them (Windows's flow genuinely differs
enough — WSL2, winget, reboot handling — that duplication there is warranted; macOS's flow is
close enough to Linux's that sharing is the better call).

## Full install-flow CI testing (all 3 platforms)

`build-installer.yml` runs a **real `install` invocation** (Podman setup, Podman Machine/
native start, image pull, compose up, health-check poll) on all 3 platforms at release time —
not just a cross-compile check or a `version` smoke test. This only exists because the repo is
**public**: standard GitHub-hosted runner minutes (Linux, Windows, *and* macOS alike) are free
and uncapped on public repos regardless of the 2x/10x-vs-Linux multiplier that applies to
private-repo paid quotas — the only real cost is wall-clock time, not money.

**Gated by `detect-installer-changes`, not run on every release.** A full install test is
expensive relative to a routine backend/frontend-only release where the installer's own code
provably didn't move. That job diffs `installer/`, `packaging/`, `compose-prod.yaml`, and the
two workflow files themselves against the *previous* release tag (`git describe --tags
--abbrev=0 "${GITHUB_REF_NAME}~1"`); no previous tag (first-ever release) defaults to "changed"
rather than silently skipping. If none of those paths moved, the 2 gated full-install jobs
(`test-linux-install`, `test-windows-install`) are skipped — `test-macos` is **not** gated by
this (it always runs, but only ever does a `version` smoke test, never a full install, see
below) — and the cheap cross-compile checks (`ci.yml`) and the Linux/macOS `version` smoke
tests still always run regardless.

**Linux runs on `ubuntu-latest`, deliberately not a Fedora-flavored environment**, even though
Fedora is this project's actual reference distro. GitHub has no Fedora-hosted runner; running
Fedora-in-a-container would need privileged nested-Podman setup (Podman managing its own
containers from inside a container) for little real benefit — `install.go`/`start.go` have no
Fedora-specific logic beyond the `dnf install` error message text, and the actual Podman/
compose behavior under test is distro-agnostic. The one genuinely Fedora-specific thing this
project has (the `:z` SELinux volume flag in `compose-prod.yaml`) is inert on Ubuntu, not a
divergent code path — same file, same behavior either way.

**`test-macos` never attempts a full `install` run — deliberately, permanently.** GitHub's own
docs state nested virtualization is unsupported on GitHub-hosted macOS runners (Intel or
Apple Silicon alike): ["Nested-virtualization is not supported due to the limitation of
Apple's Virtualization
Framework"](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), also
tracked as open, unresolved feature requests
([actions/runner-images#9460](https://github.com/actions/runner-images/issues/9460),
[#13505](https://github.com/actions/runner-images/issues/13505)). Podman Machine's `podman
machine start` needs exactly that (krunkit/Hypervisor.framework) — confirmed live, every
time: `Error: krunkit exited unexpectedly with exit code 1` /
`podman machine start: exit status 125`, right after Podman itself installed and `machine
init` succeeded. This is a **permanent platform limitation, not a flakiness problem to
iterate on** — do not re-add a full-install step to `test-macos` expecting a future fix to
make it pass; `continue-on-error` would only hide a test that can never succeed. The `version`
smoke test is the full extent of macOS CI coverage; a genuine full-install validation needs
the user's own Apple Silicon Mac.

**Windows and Linux are `continue-on-error: true` — informational, not release gates, until
proven reliable across a few real releases:**
- **`test-windows-install`**: nested virtualization for WSL2 (in turn needed for Podman
  Machine) has been confirmed working on GitHub's `windows-latest` runners by the community
  since the Dadsv5 hardware migration (Jan 2024) — but this is **not officially documented or
  guaranteed** by GitHub. **The installer's embedded `execution-level: administrator` manifest
  (see "Windows executable code signing" above) hung the job indefinitely the first two times
  this was tested** (confirmed live: 45+ minutes, zero progress, twice) — PowerShell's
  `Start-Process` launches an exe via ShellExecute, which honors that manifest by popping the
  interactive UAC consent dialog, and nobody is present to click it on a headless runner. Fix:
  run the installer through a Scheduled Task (`New-ScheduledTaskPrincipal -RunLevel Highest`)
  instead of `Start-Process` — Task Scheduler's own silent-elevation mechanism bypasses the
  interactive consent dialog entirely, without weakening the shipped manifest or a real end
  user's UAC prompt in any way. **A second, distinct hang surfaced right after this fix**: the
  install log showed every real step (WSL2/Podman/Docker Compose, `podman compose up -d`,
  shortcuts) succeed within ~3 minutes, yet the Scheduled Task still reported `Running` a full
  10 minutes later — `popupYesNo`'s final "Voulez-vous lancer maintenant ?" `MessageBox.Show`
  blocks forever with nobody to click it. Fixed at the source in `popup()`/`popupYesNo()`
  (`main_windows.go`): both skip the interactive dialog and log instead when `CI` is set in
  the environment (GitHub Actions, and virtually every other CI provider, sets `CI=true`) —
  never set on a real end user's machine, so their experience is unchanged. **Third hang, same
  symptom, after that fix**: a Scheduled Task does not inherit the calling PowerShell step's
  own process environment — Task Scheduler builds a fresh environment block for the target
  user from machine/user-scoped variables, not the caller's transient `env:` block — so
  `os.Getenv("CI")` still saw nothing and the popup still blocked. Fixed by persisting it with
  `[Environment]::SetEnvironmentVariable('CI', 'true', 'Machine')` in the workflow step
  *before* registering the task, harmless since this runner VM is destroyed right after.
- **`test-linux-install`**: lower risk (no elevation dance, no nested hypervisor), but new and
  unproven — kept `continue-on-error` for the same reason, tighten once stable. The job
  installs `podman-compose` explicitly (`pip install podman-compose`, matching `ci.yml`'s own
  compose-syntax step) — without it, `detectComposeCmd()` falls back to the `podman compose`
  subcommand, which on this runner image auto-delegates to Docker's pre-installed compose CLI
  plugin instead of using Podman's own compose implementation, and that plugin can't reach a
  Docker daemon (confirmed live). A real end-user machine without Docker installed alongside
  Podman wouldn't hit this.

Once each of these two has run clean across a handful of real releases, remove its
`continue-on-error: true` to make it a real release gate — don't leave it soft-failing forever
just because it started that way.

**Both jobs poll Quay.io before pulling — `publish-images.yml` fires off the same tag push with
no ordering guarantee.** Confirmed live on the real v1.3.0 release: `test-linux-install` failed
in 15s on "manifest unknown" and `test-windows-install` failed at the compose step, both well
before `publish-images.yml` finished pushing 4 minutes later (issue #16). Each install-test job
now has a "Wait for images to be published to Quay.io" step (polls the public
`quay.io/api/v1/repository/.../tag/` endpoint, 10-minute timeout) before invoking the installer —
chosen over reordering the two workflows via `workflow_run` (ref/context quirks) or merging them
into one (bigger restructure for a timing bug).

**`workflow_dispatch` lets this whole pipeline run on demand without creating a release.**
`build` computes `VERSION` once — a real tag version on `push`; on a manual run, the
**latest already-published release's version** instead of a made-up placeholder, since no
container image exists on Quay.io for a version nobody ever published (confirmed live:
`podman pull` failing with "manifest unknown" for a first attempt at a synthetic
`0.0.0-dispatch-<sha>` version) — and exposes it as a job output so every downstream job reads
the same value instead of re-deriving it from `GITHUB_REF_NAME` (a branch name on manual runs,
which can contain `/` and would break filenames built from it). The "Create GitHub Release"
and "Delete obsolete releases" steps are both gated `if: github.event_name == 'push'` — a
manual dispatch builds and installer-tests all 3 platforms but never touches GitHub Releases
or Quay.io.

### Changelog generation

`CHANGELOG.md` is regenerated by `git-cliff` (`cliff.toml`) on every tag push — committed to
`main` **after** the release is created and its binaries uploaded, and never fails the job on a
push error, since documentation must never block the release itself. Its newest entry is also
appended to the GitHub Release body — this is what actually survives the "Delete obsolete
releases" cleanup above, since that step only prunes GitHub Release objects, not git history.
Generation is restricted to the `v1.0.21..` commit range: tags `v1.0.1`–`v1.0.20` were deleted
during early iteration and no longer exist, so `cliff.toml`'s static **footer** (rendered last,
oldest-entry-last like every other entry, per Keep a Changelog convention) hand-documents the
initial release through `v1.0.21` as one combined entry instead of guessing at the lost
boundaries — see issue #15. Every release from `v1.0.22` onward is generated automatically and
is accurate. Commit messages must stay Conventional-Commits-formatted (`type(scope): message`)
for this to keep working — `feat`→Added, `refactor`/`perf`→Changed, `fix`→Fixed (Keep a
Changelog section order); `docs`/`chore`/`ci`/`build`/`test`/`style`/merge commits are
intentionally omitted from the changelog.

