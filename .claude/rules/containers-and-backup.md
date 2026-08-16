---
paths:
  - "backend/Containerfile"
  - "frontend/Containerfile"
  - "compose.yaml"
  - "compose-prod.yaml"
  - ".github/workflows/ci.yml"
  - "installer/common.go"
---

## Container architecture

**`backend/Containerfile` runs Python 3.14** (matches CI's `integration-tests` job — see
the root `CLAUDE.md`'s "Backend tests" section). Bumping the Python version here is not risk-free just because CI's
test job already passes on that version: CI's job does a bare `pip install` on the GitHub
runner (which ships a lot of build tooling already), it never builds this Containerfile.
When `psycopg2-binary` was pinned to a version with no prebuilt wheel for 3.14, CI stayed
green while `podman build` failed outright trying to compile it from source. Always verify a
Python-version bump by actually running `podman build -f backend/Containerfile backend/`,
not just by trusting CI.

**`backend/Containerfile` is a multi-stage build** (`builder` → `runtime`, #20) — the final
image no longer carries `pip`, `setuptools`, `build-essential`, `curl`, or `gnupg`, none of
which the app needs after `pip install` finishes at build time. This structurally closes a
class of Trivy finding that `requirements.txt` has no lever to fix: HIGH CVEs in pip's own
vendored `msgpack` and in `setuptools` itself (both ship pre-installed in the `python:3.14-slim`
base image, not from anything this Containerfile's own `RUN` steps add — see #11/#20).
`builder` installs Python deps into an isolated `--prefix=/install` (kept separate from the
base image's own pip) and stages `pg_dump`/`pg_restore` plus their full transitive
shared-library closure into `/pg-runtime/` via an `ldd`-based walk (self-computing on every
build, not a hand-maintained `.so` list that goes stale). `runtime` starts fresh from the same
base+digest, removes the base image's own pip/setuptools/wheel
(`python -m pip uninstall -y pip setuptools wheel` — uses pip's own RECORD manifest so
companion files like the `_distutils_hack` `.pth` shim are removed correctly, not a `rm -rf`
glob), then copies both artifacts in. A `RUN` step at the end of the `runtime` stage — a real
import of `app.main`/`app.tasks.pgq_app` plus `pg_dump --version`/`pg_restore --version` —
fails the build itself immediately if either copy is incomplete, instead of only surfacing at
container start. **Both `FROM` lines must be bumped to the same digest together** — a future
Dependabot base-image PR that only updates one would silently run the `builder`'s `ldd`
closure against a different glibc than the `runtime` stage ships. Verified live: real
`podman build`, a local Trivy scan confirming `msgpack`/`setuptools` are gone (present on the
old single-stage image, absent here), a ~43% image size reduction (772 MB → 439 MB), and full
`podman-compose up` smoke tests (see below) on both dev and prod-style stacks.

**`backend/Containerfile` runs as a non-root user (`appuser`, UID/GID 1000)** — fixed
issue #17 (previously ran fully as root). `appuser` never needs write access to the
application source tree: `pg_dump`/`pg_restore` (admin backup/restore) and the Excel import
only ever touch `/tmp` or memory, and nothing else in the app writes to disk at all since
Celery's removal (issue #66) — Celery Beat used to need its own schedule file redirected to
`/tmp` (see git history if resurrecting this), but that mechanism is gone along with Celery
itself. This also sidesteps host/container UID mismatches on the dev bind-mount
(`./backend:/app:z`), since reading it only relies on standard "other" read permission
bits, not an exact UID match.
Verified live (not just build success): a real `podman-compose up` in both dev
(bind-mount) and prod-style (`alembic upgrade head && uvicorn`, baked image) modes,
confirming clean startup, no permission errors, and a working backup+restore
round-trip, all as `appuser`.

**`frontend/Containerfile` runs `node:24-alpine`** (matches CI's `node-version: '24'` in
`ci.yml`). Bumped from `node:20-alpine` (2026-08) after a Trivy scan flagged an Alpine
`libssl3`/`libcrypto3` CVE (CVE-2026-45447) that a rebuild alone couldn't fix — Node 20
reached EOL 2026-04-30 and Docker Hub stopped rebuilding `node:20-alpine` shortly before,
so its baked-in Alpine packages were permanently frozen pre-fix. Verified via real
`podman run` + `apk list --installed` that `node:22-alpine`/`node:24-alpine` (both actively
rebuilt) already carry the fixed `openssl` packages. If a future CVE report on this image
assumes "just rebuild it", check the base tag's actual last-push date on Docker Hub first —
an EOL runtime's official image can silently stop receiving any OS-level security rebuilds.

**Do not bump `node:24-alpine` → `node:26-alpine` before Node 26 reaches Active LTS
(2026-10-28) — tracked in #57.** Dependabot PR #29 proposing this was closed (not
`@dependabot ignore`d) rather than merged: the bump itself builds and runs cleanly (verified
live), but Node 24 is Active LTS until 2026-10-20 / Maintenance until 2028-04-30, while Node 26
is still on the less battle-tested "Current" release line until its LTS date. No urgency to
take on that risk early. Dependabot's own weekly scan will re-propose an equivalent PR on its
own — merge it once Node 26 is actually Active LTS, don't defer indefinitely.

**`frontend/Containerfile` is a multi-stage build** (`builder` → `runtime`, #13), mirroring
the backend's #20 refactor for the same reason: `builder` runs `npm ci` (now copies
`package-lock.json` before install too — previously only `package.json` was copied, so the
image's `npm install` silently ignored the pinned lockfile and re-resolved from the registry
at build time, picking up whatever transitive versions happened to be current) and the app
source; `runtime` starts fresh from the same base+digest, deletes the base image's own bundled
npm CLI (`rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx`) before
copying in `builder`'s `/app`. This structurally removes a class of Trivy finding
`package.json` has no lever to fix: HIGH/CRITICAL CVEs in npm's own vendored `tar`/
`brace-expansion`/`ip-address`/`undici` (pre-installed in the `node:24-alpine` base image, not
from anything this app's own dependencies pull in — confirmed by locating them under
`/usr/local/lib/node_modules/npm/node_modules/`, not `app/node_modules/`). Safe to remove
because the dev server is invoked via its own binary (`node_modules/.bin/vite`, both in the
Containerfile's `CMD` and in `compose.yaml`'s dev override), never via `npm run` — `node`
itself doesn't depend on npm's bundled `node_modules` at runtime. Verified: real
`podman build`, a from-scratch Trivy scan going from 4 HIGH/CRITICAL findings to 0, and a full
`podman-compose up` smoke test (dev stack, isolated project name) confirming the Vite dev
server still starts and serves the app correctly. As with the backend, **both `FROM` lines
must be bumped to the same digest together** on a future base-image update.

### Development (compose.yaml)

```
compose.yaml
├── postgres (PostgreSQL 16)
├── backend (FastAPI)
├── pgq-worker (PgQueuer, `pgq run app.tasks.pgq_app:main`)
└── frontend (Vite dev server, port 5173)
```

### Production (compose-prod.yaml)

```
compose-prod.yaml
├── postgres (PostgreSQL 16)             restart: unless-stopped
├── backend (FastAPI)                    restart: unless-stopped, no exposed ports
├── pgq-worker (PgQueuer)                restart: unless-stopped
├── frontend (Vite dev server)           restart: unless-stopped, no exposed ports
└── haproxy (reverse proxy)              restart: unless-stopped, port APP_PORT:8080
```

In production, **HAProxy** is the single public entry point. It routes:
- `/api/*` → `backend:8000` (FastAPI) — active health check on `/api/admin/health`
- `/*` → `frontend:5173` (Vite dev server)

Backend and frontend containers have no exposed ports — all traffic flows through HAProxy.
HAProxy uses `parse-resolv-conf` + `resolve-prefer ipv4` to handle Podman's DNS correctly
on both Docker (127.0.0.11) and Podman (gateway IP) environments.

### Port selection (production)

Default port: **14943** (constant `defaultPort` in `installer/common.go`).

At install time, `findAvailablePort(14943)` scans from 14943 upward for the first free TCP port. The chosen port is written to `~/.local/share/pie-manager/.env` as `APP_PORT=<n>`. At subsequent starts, `runStart()` reads `APP_PORT` from `.env` and checks whether it is still free; if not, it picks a new port and rewrites `.env`.

The `.env` file also holds `APP_VERSION=<n>`. Both variables are consumed by `compose-prod.yaml` via `${APP_PORT:-14943}` and `${APP_VERSION:-dev}`.

## Database backup

- Endpoint `GET /api/admin/backup` → calls `pg_dump` via `subprocess` from the backend container
- Endpoint `POST /api/admin/restore` → `pg_restore --clean --if-exists --no-owner --no-privileges`
  — deliberately **no** `--single-transaction`: it would fail the whole restore on a
  non-critical `transaction_timeout` error emitted by dumps taken with a pg_dump newer than
  PostgreSQL 16 (a documented pg_restore quirk, not something to "fix" by adding the flag back)
- Format `.dump` (custom binary pg_dump, compressed)
- `backend/Containerfile` pins `postgresql-client-16` to match the server (PostgreSQL 16) — a
  mismatched client version produces dumps the server's own pg_restore can't read

**A PostgreSQL major-version bump (e.g. 16→18) is not a simple image-tag swap — do not merge
one via Dependabot without a real migration plan (tracked in #58).** Confirmed live: `postgres:18-alpine`'s
official image changed its volume mount convention (a single mount at `/var/lib/postgresql`
with a version-scoped subdirectory, instead of today's direct mount at
`/var/lib/postgresql/data`) — it refuses to even start on a **fresh, empty** volume under the
current `compose.yaml`/`compose-prod.yaml` mount layout, let alone an existing data volume.
A v16 `pg_dump` client also flatly refuses to dump a v18 server (`aborting because of server
version mismatch`), so the pinned client above must be bumped in lockstep. A dump/restore
migration path (matching-version dump, then restore into a fresh volume under the new mount
layout with a matching-or-newer client) was verified to work end-to-end on a throwaway volume
— but treat any future postgres major bump as its own migration project (compose changes +
client bump + a tested, documented upgrade path for existing installs, including real
end-users of the published installer), never a routine dependency bump.

