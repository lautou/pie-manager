# Native launcher PoC

Throwaway diagnostic build for [issue #82](https://github.com/lautou/pie-manager/issues/82) —
not part of the shipped product, never built or referenced by the real installer. Mirrors the
packaging/sideload/cleanup mechanics already proven in #76's `msix-postgres-elevation-poc` (same
manifest shape, same ephemeral-cert approach) — see that poc's own README for the shared
mechanics; this one only documents what's different.

## What this tests

Everything in `installer/launcher-native/` (the real orchestration code for #82's native-Windows-
port MVP — see that package's own doc comments) was unit-tested and cross-compiled during
development, but never actually run inside a real full-trust MSIX package on a real Windows
machine. This poc is that first real end-to-end test: the actual `launcher-native.exe` (not a
throwaway test stub), packaged with a bundled Postgres, a bundled embeddable Python, and — new
compared to #76's poc — the **real backend source** (`backend/app/`, `alembic.ini`, `alembic/`),
so the whole flow (`initdb` → `pg_ctl start` → `createdb` → `alembic upgrade head` → spawn
`uvicorn` → health poll) runs against the genuine application, not a minimal stand-in.

**Extended a second time**: also builds the real frontend (`npm run build`) and stages it into
the package as `frontend_dist/`, so `app/frontend.py`'s `mount_frontend` (see that module's own
docstring) actually serves the genuine, built React app — not just a 404 on `/` — once the
backend is up. Verified locally first (real `uvicorn` + real built `dist/` + a throwaway
Postgres, `curl` against `/`, a real asset, an SPA deep link, `/api/*`, and two path-traversal
attempts) before ever touching the win11 VM — see the commit history for that log.

## Unlike #76's poc, this one has no built-in result-reporting mechanism

`launcher-native.exe` is the real, shipping-candidate code — it deliberately has no
test-only diagnostic output baked in (unlike #76's poc's `worker.ps1`, which existed purely to
report PASS/FAIL). Verification instead reads the real log files `startupSequence` already
writes for its own operational purposes, at `%USERPROFILE%\PieManager\logs\` — a real,
non-package-scoped, externally-visible location (confirmed in #82's own persistence-verification
work): `initdb.log`, `pgctl-start.log`, `createdb.log`, `alembic.log`, `backend.log`. A
screenshot of the WebView2 window itself is the other half of verification — confirming the
window actually navigated to the running app, not just that the backend became healthy.

## Re-running the verification

```
gh workflow run native-launcher-poc.yml --repo lautou/pie-manager --ref feature/82-native-windows-mvp
gh run watch --repo lautou/pie-manager
```

Then transfer `poc.msix`/`cert.cer` to the win11 VM the same way as #76's poc (ISO-based, see
that poc's README's Phase 2 section) — sideload, launch via its AUMID
(`PieManagerNativeLauncherPoc_<hash>!App`), then inspect the log files above and a screenshot.
