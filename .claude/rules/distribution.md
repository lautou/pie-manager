---
paths:
  - "installer/**"
  - "packaging/**"
  - "backend/app/frontend.py"
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

**Real release gate since #21** (`exit-code: 1`, no `continue-on-error`) — the filtered scan ran
clean (0 findings) across 6 consecutive releases (v1.3.2 through v1.4.3) before this was flipped,
mirroring `test-linux-install`'s progressive-hardening pattern below.

**Scans happen BEFORE push, not after — this matters, don't revert to post-push scanning.**
Each image is built, saved to a local tarball (`podman save`), and scanned from that tarball via
Trivy's `input:` option before any `podman push` runs. The previous layout scanned the
already-pushed `image-ref:` from the registry — with `exit-code: 1` that would only fail the CI
run *after* a vulnerable image was already public on Quay.io, since a job failure can't retract a
push. `input:` (a local tar produced by `podman save`) is the scan path Trivy's own docs actually
document for a local, unpushed image; `image-ref:`'s registry-vs-local-daemon auto-detection is
undocumented for Podman specifically, so it isn't relied on. Gating only `:latest` was considered
and rejected too — `compose-prod.yaml`/the installer always pin the exact version tag, never
`:latest`, so a real end-user install would never have been protected by that alone.

### Backend backup/restore smoke test (`smoke-test-backend`, #45)

`publish-images.yml`'s `smoke-test-backend` job (`needs: publish`, `continue-on-error: true` —
same progressive-hardening pattern as `test-linux-install`) runs a real
`pg_dump`/`pg_restore` round-trip against the just-published backend image: starts a real
`postgres:18-alpine` GitHub Actions service (no volume mount at all — a GitHub Actions service
container uses its own ephemeral storage, so the PGDATA/mount-layout fix documented in the
root `CLAUDE.md`'s "Database backup" section doesn't apply here), runs the image via
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

### MSIX/Microsoft Store distribution of launcher.exe alone — investigated and rejected (issue #63)

**Historical background** (the old WSL2/Podman `launcher.exe`/`pie-manager-windows-amd64.exe`
path this section originally describes was fully retired in issue #84 — see "Windows
installation architecture" below for the current, native/Store-only replacement). Kept here
because the decision trail — why a hybrid "Store app that downloads/elevates a separate
installer" design doesn't work — remains true regardless of what the old path's own code looked
like, and the SAC-block finding below was the direct trigger for building #82's native launcher
in the first place: Smart App Control (SAC) could hard-block the old, self-signed
`CN=PIEManager`-Authenticode-signed `launcher.exe` outright on a fresh Windows 11 install, with
no override, no local-trust-store workaround, and no fix short of a real CA-issued certificate
(confirmed live, issue #60) — because SAC only accepts signatures chained to a CA in the
Microsoft Trusted Root Program.

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
no WSL2/Podman at all) — it landed, passed real Store certification, and is now the only
Windows distribution path (issue #84 retired the old WSL2/Podman installer once #82/#83 were
verified stable). SAC is no longer a concern at all for this app: Store-distributed apps bypass
SAC/SmartScreen by design.

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
%USERPROFILE%\PieManager\   pgdata (Postgres data dir), pgsql\ (bundled Postgres binaries)
%USERPROFILE%\PieManager\   python\ (bundled embeddable Python + backend app + frontend_dist)
%USERPROFILE%\PieManager\   logs\ (backend.log, postgres.log, worker.log, etc.)
Start Menu                  PIE Manager  (Store-installed MSIX, → launcher-native.exe)
```
Deliberately never under `AppData`/`LocalAppData` — MSIX transparently redirects any write
there to a location wiped on uninstall (confirmed live, #76/#82).

### `app/frontend.py`'s `mount_frontend` must set `Cache-Control: no-cache` on `index.html`

The native launcher's WebView2 instance is a **persistent** browser profile (not ephemeral like
a normal CI/ad hoc test) — it survives across app restarts and even MSIX reinstalls, since the
profile lives outside `frontend_dist` entirely. `index.html` is requested at a stable, unhashed
URL (`/`), unlike Vite's content-hashed asset filenames — a client that caches it without
revalidating will keep serving a stale index.html (and therefore stale asset references)
indefinitely, no matter how many times `frontend_dist` is rebuilt and correctly re-staged on
disk. Confirmed live (issue #118): a real multi-round investigation where every single test
appeared to still be running a build from an earlier session, even after independently verifying
that *both* the installed MSIX's own `frontend_dist` and the staged writable copy under
`%USERPROFILE%\PieManager\frontend_dist` had the correct, up-to-date files — the browser simply
never re-requested `index.html` from the server at all.

**Fix**: `mount_frontend`'s `FileResponse` calls now set `Cache-Control: no-cache` explicitly
for `index.html` (forces revalidation via the ETag/Last-Modified `FileResponse` already sets —
cheap 304 if unchanged, fresh fetch if not) and `public, max-age=31536000, immutable` for
everything else under `/assets/` (safe, since Vite's content-hash filenames never reuse a URL
for different content). Without an explicit header, `FileResponse`'s default leaves caching up
to the client's own heuristics, which can pick an arbitrarily long freshness lifetime — this is
not a hypothetical, it's what actually happened here. If `mount_frontend` is ever rewritten
(e.g., swapped for `StaticFiles`), preserve this exact split — don't let index.html fall back to
default/heuristic caching again.

### Installed files (macOS)
```
~/Library/Application Support/PieManager/   compose-prod.yaml, haproxy.cfg, .env, pie-manager (binary), VERSION
~/Library/LaunchAgents/                     com.pie-manager.podman-start.plist
~/Applications/                             PIE Manager.app  (Contents/MacOS/pie-manager-launcher)
~/.local/bin/                               pie-manager (symlink)
```

### Windows installation architecture (native, Store-distributed — issue #82/#83/#84)

On Windows, PIE Manager is distributed exclusively through the Microsoft Store
(`installer/launcher-native/`, PFN `PIEManager.PIEManager_9h5hzpm8nc7w0`, Store ID
`9PM8GPSMJG0N`) as a single self-contained MSIX package. No WSL2, no Podman, no containers, no
elevation: the package bundles its own Postgres binaries and an embeddable Python interpreter
running the real backend directly as native child processes, orchestrated by
`launcher-native.exe` (a WebView2 GUI shell). This fully replaced the old WSL2/Podman/winget
installer in issue #84, once #82/#83 were verified stable — see the `#63` section above for why
a hybrid Store-app-plus-elevated-installer design was never viable, and the root `CLAUDE.md`'s
"Installer test coverage policy" section (the `launcher-native/` entry) for the actual
architecture: process orchestration, Postgres readiness (`pg_isready`, not a raw TCP dial),
console-window suppression, the PgQueuer worker, and this module's own CI coverage (#114).

Auto-update is handled entirely by the Microsoft Store, like any other Store app — no
in-app update mechanism, no Scheduled Task, no manual re-run needed.

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

### Local win11 test VM (`installer/testing/`) — maintenance notes

A local libvirt/QEMU Windows 11 VM (separate from `package-native-launcher-msix`'s
GitHub-hosted CI runner above) is used for hands-on, real-hardware-adjacent testing of the
native launcher — UAC prompts, Smart App Control, the MSIX install/launch, etc. Built and
rebuilt via 3 scripts, run in order (see `installer/testing/README.md` for the exact commands):

- **`00-download-win11-iso.py`** — fetches the real, official Windows 11 x64 multi-edition ISO
  directly from Microsoft's own CDN, replaying the same internal API calls the official
  download page's own JavaScript makes (session whitelisting via `vlscppe.microsoft.com`, an
  anti-bot handshake via `ov-df.microsoft.com`, then the software-download-connector API for
  the real, time-limited download link). Same technique as the well-known open-source tool
  [Fido](https://github.com/pbatard/Fido), ported to plain Python (stdlib only) because Fido's
  own command-line mode explicitly refuses to run on non-Windows platforms, even though none
  of the underlying HTTP calls are Windows-specific. **This is inherently fragile** — it relies
  on Microsoft's undocumented internal API, which has already changed shape once (an
  `ov-df.microsoft.com` anti-bot step was added after the flow's simpler original form). If it
  starts failing, re-derive the current sequence from Fido's own up-to-date source rather than
  guessing or patching around symptoms — that project is actively maintained specifically to
  track Microsoft's changes to this flow.
- **`01-create-vm.sh`** — creates the VM (NOCOW disk, correct CPU model, TPM 2.0, UEFI Secure
  Boot, guest-agent virtio-serial channel) and runs a **fully unattended** Windows install via
  `autounattend.xml` (issue #61, validated live): driver injection (`viostor`), a local account
  instead of a Microsoft account, a silent `virtio-win-guest-tools` install, and an automatic
  shutdown — no GUI, no manual clicks, the script itself polls for that shutdown. Idempotent:
  re-running it tears down any existing VM of the same name (surgically — only the VM's own
  qcow2 volume, never `--remove-all-storage`, which was confirmed live to delete the *shared*
  `virtio-win.iso` pool volume too) and rebuilds from scratch. `sudo` is only needed the very
  first time ever on a host (to prepare the NOCOW directory); every later rebuild runs
  unprivileged. Two non-obvious fixes baked in after live testing: (1) libvirt's
  `dynamic_ownership` means the unprivileged `qemu` process needs `x` (search) permission on
  every ancestor directory of the ISO path, not just read on the file itself — a `710` home
  directory silently blocked this, fixed via a self-healing ACL loop (`setfacl`, no root
  needed since it's the invoking user's own directory); (2) Microsoft's `bootmgfw.efi` shows an
  interactive "press any key to boot from CD or DVD" prompt with a short, easy-to-miss timeout —
  a single well-timed `send-key` reliably missed it, fixed by spamming `KEY_ENTER` for ~30s
  right after the domain starts.
- **`02-tune-and-snapshot.sh`** — pushes and runs **`tune-guest.ps1`** (the "debloat" script:
  disables telemetry/Xbox/Widgets services and scheduled tasks, removes bundled AppX bloat,
  sets the High Performance power plan, adds Windows Defender exclusions for WSL2/Podman
  paths — NOT the native launcher's own `%USERPROFILE%\PieManager\` path, so it doesn't
  interfere with any Defender-related testing of that installer's own first-run behavior),
  then takes a reusable `base-clean-tuned-<date>` snapshot. Untouched by #61's Setup-automation
  work — it only runs after Setup already completes, regardless of how Setup itself gets there.
  Verified live: this baseline has zero pre-trusted certificates and zero private keys anywhere
  (`Root`/`TrustedPublisher`/`My`) — the polluted, manually-modified snapshot issue #62
  originally found is gone for good now that the whole VM is rebuilt from scratch via #61.

Issue #62's other proposal — an opt-in `03-import-signing-cert.sh` to test "what if the user
already trusts our self-signed cert" (UAC's verified-publisher display) — was considered and
explicitly **not implemented**: a full-trust MSIX never triggers UAC at all unless it declares
`allowElevation` + `requireAdministrator` (the native launcher does neither — its bundled
Postgres refuses to even run elevated), and a locally-trusted self-signed cert does nothing for
SmartScreen either way (that needs real accumulated download reputation, regardless of cert
type). The old `launcher.exe`/Podman product this test would have covered has zero real
deployed users, so there's nothing left for this scenario to actually validate. #60 and #62 were
closed on this reasoning rather than left open waiting on #84.

#### Automating win11 test VM checks: `virsh`/guest-agent is the default, RDP is a last resort

**Default for essentially all non-regression testing: `virsh qemu-agent-command` (the
guest-agent channel already configured on this VM, see the channel device in its domain XML) —
transferring files, running installers, checking process/service state, reading logs, polling a
health endpoint. This needs no extra host packages and stays the standing approach going
forward.** Confirmed live (issue #82's Store-install verification, 2026-08-19): guest-agent
alone drove snapshot revert, boot-readiness polling, chunked file transfer (`guest-file-open`/
`guest-file-write`/`guest-file-close` — small chunks, ~48 KiB; a 512 KiB chunk hit the host
shell's own `ARG_MAX` via `subprocess.run`'s argument list, not a QGA limit), PowerShell
execution, and process/log inspection, entirely unattended.

**The one thing guest-agent structurally cannot do: answer any question that requires a real,
visible GUI session.** Two independent, unrelated Windows OS restrictions make this a hard wall,
not a scripting gap to work around:
1. `Add-AppxPackage` (installing a Store app's MSIX, or any AppX operation) refuses outright
   under the SYSTEM account guest-agent always runs as — confirmed live, "le compte Système
   local n'est pas autorisé à effectuer cette opération."
2. SYSTEM's guest-agent process runs in **Session 0**, which is deliberately isolated from the
   interactive user's session (Session 1) for security reasons — confirmed both live (a
   SYSTEM-side `EnumWindows` Win32 call returned zero windows despite windows visibly on
   screen) and via external sources: Microsoft's own Session 0 Isolation documentation, and a
   real production CI engineering write-up (SEP, testing Windows desktop GUI apps) hitting this
   exact wall and confirming modern Windows additionally **strips keyboard/mouse input from
   Session 0 entirely** — not just window enumeration, input itself is dead there. Their
   production fix was RDP + PsExec-style session injection — same shape of solution as below,
   independently arrived at.

**Two escalation tiers below full RDP, try both first:**
- **`virsh screenshot <vm> out.png`** reads the emulated video device's framebuffer directly —
  this is *not* subject to Session 0 isolation at all, since it's a hypervisor-level capture, not
  a Windows API call. Sufficient for "does the expected screen/dialog look right" checks with no
  interactive control needed.
- **A guest-agent-written Startup-folder script** (`%USERPROFILE%\...\Startup\*.cmd`, one-shot,
  runs automatically when the target user's session starts) combined with **`virsh send-key`**
  to log that user in (numeric/PIN-style password strongly recommended — see the keyboard-layout
  gotcha below) gets a script running as a *real interactive user* without ever needing mouse
  control or an RDP client. This is exactly how the Store/`winget` install verification worked
  (issue #82) — no RDP involved at all for that part. **Requires explicit, specifically-scoped
  user authorization each time** — Claude Code's own permission classifier correctly treats
  writing to a Startup folder (or a scheduled task with embedded credentials) as a persistence
  mechanism, not something to reuse silently just because a similar action was approved before.

**Full RDP (`xfreerdp` + a throwaway `Xvfb` display + `xdotool` for mouse/keyboard) is the
last-resort tier — reach for it only when a check genuinely requires interactive, unpredictable
GUI navigation (clicking through multiple screens) that a fixed Startup-folder script can't
express as a fixed sequence.** Not part of the standing toolchain: `freerdp`, `xorg-x11-server-
Xvfb`, and `xdotool` were installed on the dev host ad hoc for the one investigation that needed
real visual confirmation of window visibility (issue #82's console-window bug) and are not a
CI/pipeline dependency — don't provision them preemptively for routine testing.

**Keyboard-layout gotcha, hits both `virsh send-key` and `xdotool type` identically:** both send
scancodes/keysyms based on the *local host's* keymap; the *guest's* active layout (French/AZERTY
on this VM) then reinterprets them, silently corrupting any typed text containing letters that
differ in position between AZERTY and QWERTY (confirmed live: "powershell" → "pozershell", a
password typed via top-row digits needing Shift on AZERTY silently mismatching). Two fixes, use
either: (1) type only numpad digits (`KEY_KP0`-`KEY_KP9` — layout-independent, requires NumLock
on first) for anything password-like; (2) switch the guest's active input method to en-US via
`Set-WinUserLanguageList` over guest-agent before typing anything with letters.

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
`githubLatestAssetURL` (`common.go`) now passes `GITHUB_TOKEN`/`GH_TOKEN` as a bearer token
when present in the environment — shared GitHub Actions runner IPs can already be near the
unauthenticated GitHub API's 60/hour limit (confirmed live: a real 403), while a real end
user's install never has this env var set.

**`configurePodmanRestartService()`'s `podman machine ssh` call must pass the whole
`&&`-chained compound command as the sole trailing argument, never split as separate
`"bash","-c",cmd` arguments.** `podman machine ssh` mangles a compound command passed that way
— confirmed live and matches an independent upstream report
([containers/podman#13517](https://github.com/containers/podman/issues/13517)): it re-joins
multiple trailing arguments before forwarding them over SSH, so `bash`, `-c`, and the command
string arrive at the remote shell re-split on whitespace — only the first word after `-c`
survives as its actual script argument. Pass the full compound command as one string after
`--` instead — the remote SSH server already wraps a single command string in a shell itself.

**Auto-start at login uses a `launchd` LaunchAgent.**
`~/Library/LaunchAgents/com.pie-manager.podman-start.plist` (`RunAtLoad`) runs `podman machine
start` at login, loaded/unloaded via `launchctl load`/`unload`.

**No native WebView launcher for v1 — `open <url>` (default browser), matching Linux's own
fallback path.** The native Windows launcher (`installer/launcher-native/`) uses
`go-webview2`, a cgo-free binding to the
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
them. Windows has no equivalent to share with: the native launcher (`installer/launcher-native/`)
is an entirely separate module with its own architecture (bundled Postgres + Python, no
Podman/compose/image-pull concept at all), not a variant of this Podman-based install flow.

**PostgreSQL major-version mismatch guard (issue #58), Linux + macOS only.** Before
`runInstall` pulls any new image on an upgrade, it checks whether the existing data volume's
Postgres major version differs from the one the new `compose-prod.yaml` is about to start —
see the root `CLAUDE.md`'s "Database backup" section for the full mechanism and why this
exists. The old WSL2/Podman Windows install path this guard was never extended to has since
been fully removed (issue #84). The native Windows launcher bundles its own fixed-version
Postgres binaries rather than pulling a Dependabot-tracked image tag, so this specific
mismatch scenario doesn't apply there the same way — no equivalent guard exists for it yet,
and none is currently planned.

## Install-flow CI testing (Linux full install; macOS/native-Windows smoke tests)

`build-installer.yml` runs a **real `install` invocation** (Podman setup, image pull, compose
up, health-check poll) for Linux at release time — not just a cross-compile check or a
`version` smoke test. This only exists because the repo is **public**: standard GitHub-hosted
runner minutes are free and uncapped on public repos regardless of the 2x/10x-vs-Linux
multiplier that applies to private-repo paid quotas — the only real cost is wall-clock time,
not money. Windows has no equivalent full-install job of this kind anymore — the native
launcher's own install+launch validation is a real MSIX package install + app launch, covered
by `package-native-launcher-msix`'s own smoke test (see CLAUDE.md's `launcher-native/`
coverage-policy section), not this Podman-based flow at all (issue #84 removed the old
WSL2/Podman `test-windows-install` job along with the install path it tested).

**Gated by `detect-installer-changes`, not run on every release.** A full install test is
expensive relative to a routine backend/frontend-only release where the installer's own code
provably didn't move. That job diffs `installer/`, `packaging/`, `compose-prod.yaml`, and the
two workflow files themselves against the *previous* release tag (`git describe --tags
--abbrev=0 "${GITHUB_REF_NAME}~1"`); no previous tag (first-ever release) defaults to "changed"
rather than silently skipping. If that path didn't move, the gated `test-linux-install` job is
skipped — `test-macos` is **not** gated by this (it always runs, but only ever does a
`version` smoke test, never a full install, see below) — and the cheap cross-compile checks
(`ci.yml`) and the Linux/macOS `version` smoke tests still always run regardless.

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

**`test-linux-install` is `continue-on-error: true` — informational, not a release gate, until
proven reliable across a few real releases.** Lower risk than the old Windows job ever was (no
elevation dance, no nested hypervisor), but new and unproven when first added — kept
`continue-on-error` for that reason, tighten once stable. The job installs `podman-compose`
explicitly (`pip install podman-compose`, matching `ci.yml`'s own compose-syntax step) —
without it, `detectComposeCmd()` falls back to the `podman compose` subcommand, which on this
runner image auto-delegates to Docker's pre-installed compose CLI plugin instead of using
Podman's own compose implementation, and that plugin can't reach a Docker daemon (confirmed
live). A real end-user machine without Docker installed alongside Podman wouldn't hit this.

Once it has run clean across a handful of real releases, remove its `continue-on-error: true`
to make it a real release gate — don't leave it soft-failing forever just because it started
that way.

**`test-linux-install` polls Quay.io before pulling — `publish-images.yml` fires off the same
tag push with no ordering guarantee.** Confirmed live on the real v1.3.0 release: the job
failed in 15s on "manifest unknown," well before `publish-images.yml` finished pushing 4
minutes later (issue #16). It now has a "Wait for images to be published to Quay.io" step
(polls the public `quay.io/api/v1/repository/.../tag/` endpoint, 10-minute timeout) before
invoking the installer — chosen over reordering the two workflows via `workflow_run` (ref/
context quirks) or merging them into one (bigger restructure for a timing bug).

**`workflow_dispatch` lets this whole pipeline run on demand without creating a release.**
`build` computes `VERSION` once — a real tag version on `push`; on a manual run, the
**latest already-published release's version** instead of a made-up placeholder, since no
container image exists on Quay.io for a version nobody ever published (confirmed live:
`podman pull` failing with "manifest unknown" for a first attempt at a synthetic
`0.0.0-dispatch-<sha>` version) — and exposes it as a job output so every downstream job reads
the same value instead of re-deriving it from `GITHUB_REF_NAME` (a branch name on manual runs,
which can contain `/` and would break filenames built from it). The "Create GitHub Release"
and "Delete obsolete releases" steps are both gated `if: github.event_name == 'push'` — a
manual dispatch builds and installer-tests both Linux and macOS but never touches GitHub
Releases or Quay.io.

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

