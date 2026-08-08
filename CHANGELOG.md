# Changelog

All notable changes to PIE Manager are documented in this file.
## [1.3.0] - 2026-08-08

### Added

- **installer:** Add macOS (Apple Silicon) installer
- **indicators:** Add country market performance leaderboard with index-label legend
- **ci:** Auto-generate CHANGELOG.md via git-cliff on release

### Changed

- **indicators:** Extract shared Yahoo Finance fetch and Redis sync-status helpers

### Fixed

- **installer:** Scope main.syso to Windows builds only
- **ci:** Stop silently swallowing non-final && chain failures in ci.yml
- **installer:** Fix macOS Podman PATH and dispatch-test image version
- **installer:** Fix GitHub API rate-limiting and Linux compose fallback in CI
- **installer:** Fix Windows CI install hang via Scheduled Task elevation
- **installer:** Skip blocking popups in CI, bump download-artifact to v8
- **installer:** Persist CI=true machine-wide so the Scheduled Task sees it
- **indicators:** Add index_label to queries.test.ts CountryPerfConfig fixtures
- **frontend:** Bump Containerfile to node:24-alpine for OpenSSL CVE

## [1.2.11] - 2026-08-08

### Fixed

- **rebalancing:** Compute injection sufficiency server-side, add configurable severity thresholds

## [1.2.10] - 2026-07-17

### Fixed

- **launcher:** Show PIE Manager icon in the window title bar

## [1.2.9] - 2026-07-17

### Fixed

- **installer:** Quiet WSL install output and suppress OOBE welcome popup

## [1.2.8] - 2026-07-16

### Fixed

- **installer:** Verify WSL2 engine actually works, not just feature flags

## [1.2.7] - 2026-07-16

### Fixed

- **installer:** Make popups topmost and register a single resume mechanism

## [1.2.6] - 2026-07-16

### Fixed

- **installer:** Prevent concurrent instances when RunOnce and the resume Scheduled Task both fire

## [1.2.5] - 2026-07-16

### Added

- **installer:** Ask to launch PIE Manager on success, add missing desktop shortcut

## [1.2.4] - 2026-07-16

### Added

- **transactions:** Bulk Excel import with preview, dedup, and atomic commit
- **portfolio:** Add Importer shortcut button to portfolio selection cards

### Fixed

- **installer:** Tolerate already-newer AppX packages in Add-AppxPackage fallback
- **installer:** Fix RunOnce PathNotFound and podman machine ssh command mangling
- **installer:** Populate VersionInfo metadata and add Scheduled Task RunOnce fallback

## [1.2.3] - 2026-07-15

### Added

- **installer:** Authenticode-sign Windows executables with timestamp

## [1.2.2] - 2026-07-14

### Fixed

- **indicators:** Restore native-selection prevention, reset button, and tick format on macro charts; unify hover tooltip with Performance

## [1.2.1] - 2026-07-14

### Fixed

- **indicators:** Correct drag-to-zoom scale + add preset period buttons

## [1.2.0] - 2026-07-14

### Added

- **holdings:** ETF look-through composition + pool sector/company allocation
- **indicators:** Add macro indicators page with dynamic user-managed regions

### Fixed

- **lint:** Move TypeVar assignment after imports (Ruff E402)

## [1.1.0] - 2026-07-13

### Added

- **products:** Product/Transaction typology refactor (instrument_type, fee_type, operation)

## [1.0.25] - 2026-07-13

### Fixed

- **transactions:** Apply cash_balance_eur delta when date+amount change together
- **rebalancing:** Compute "après" % against total_current in full-rebalance mode

## [1.0.24] - 2026-07-13

### Fixed

- **transactions:** Exclude forex-position trades from cash_balance_eur

## [1.0.23] - 2026-07-13

### Added

- **sync:** Precise refresh on price sync completion + sync at startup

### Changed

- **frontend:** Replace window.confirm with PatternFly ConfirmModal

### Fixed

- **transactions:** Compute balance_eur for recreated linked fees on update
- **transactions:** Scope balance_eur lookups by portfolio_id
- **tests:** Fix stale-mock leak hiding SystemAdminPage coverage, close RefreshBanner gap
- **commission:** Handle sale-rate PUT errors, close row-level edit coverage

## [1.0.22] - 2026-07-05

### Added

- **transactions:** JPYEUR=X form UX + balance_currency for non-EUR positions

### Fixed

- **coverage:** Suppress unreachable False branch in holdings downsampling
- **coverage:** Replace redundant elif with else for sibling balance_currency

## [1.0.0 – 1.0.21] - 2026-05-31 to 2026-06-05

_Early development history. Individual version tags between v1.0.1 and
v1.0.20 were deleted during early iteration and no longer exist, so this
entry combines every change from the initial public release through
v1.0.21 rather than guessing at the lost boundaries. Every release from
v1.0.22 onward (above) has an accurate, individually generated entry._

### Added

- Launcher.ps1 — Edge --app mode, proper wait loop, clean shortcut
- Externalize app version via INSTALLER_VERSION env var
- Migrate container registry from ghcr.io to quay.io
- **windows:** Auto-start Podman Machine at Windows login
- **windows:** Add prerequisite installer for WSL2 + Podman setup
- Replace nginx with HAProxy, merge Windows installer, add /health endpoint
- **frontend:** Broker UX improvements + deposit form + refresh banner fix
- **windows:** Replace Edge --app launcher with native WebView2 Go binary
- **launcher:** Dynamic status messages + remove fixed timeout

### Fixed

- Install podman-compose via dnf+pip in Podman Machine at every install
- Use full path for podman-compose inside WSL machine
- Use 'podman machine ssh' instead of 'wsl -d' for compose commands
- Use 'cmd /c start' to open browser on Windows
- Use rundll32 url.dll to open browser on Windows
- Shortcut uses PowerShell to start app + open browser reliably
- On Windows, browser is opened by launcher.ps1 only
- Launcher.ps1 brings existing PIE Manager window to front
- Date format DD/MM/YYYY in manual price and transaction forms
- **ci:** Strip v prefix from VERSION in publish-images workflow
- Remove unused TextInput import in ManualPricePage
- **test:** Correct URL for daily-holding-values endpoint
- **windows:** Convert WSL compose path in pure Go, no SSH wslpath call
- **windows:** Use 'podman compose' (native) instead of pip podman-compose
- **windows:** Pause on exit + log install path + error on .env write
- **installer:** Survive pull failure on upgrade — keep existing container images
- **windows:** Start Podman Machine before compose on pie-manager start
- **installer:** Correct image registry from ghcr.io to quay.io
- **haproxy:** Bind on port 8080 instead of 80 — rootless Podman cannot bind privileged ports
- **haproxy:** Use http-check connect syntax for HAProxy 3.x active health checks
- **haproxy:** Use TCP check + purge unused images after upgrade
- **haproxy:** Resolve IPv4/IPv6 dual-stack issue with docker_dns resolver
- **haproxy:** Use parse-resolv-conf for portable DNS resolution
- **haproxy:** Use fully qualified image name for Fedora compatibility
- **installer:** Use fully qualified image names for all Docker Hub images
- **installer:** Targeted image cleanup + compose hardening
- **windows:** Enable podman-restart.service via symlink instead of systemctl
- **windows:** Retry podman machine start — WSL2 may not be ready at login
- **launcher:** Suppress console window for podman subprocess

### Changed

- **installer:** Move readAppPort to common.go for cross-platform reuse
