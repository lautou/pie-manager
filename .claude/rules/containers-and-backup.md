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

**Both `Containerfile`s pull OS security patches at build time** (`apt-get upgrade -y` for
backend/Debian, `apk upgrade --no-cache` for frontend/Alpine), added after #21 turned Trivy into
a real release-blocking gate. A digest-pinned base image is frozen at whatever OS package
snapshot existed when that digest was built — real incident: the week #21 shipped, Debian's
security repo had already published a fix for a HIGH CVE in `util-linux`/`bsdutils` (present in
the pinned `python:3.14-slim` digest) well before Docker Hub got around to rebuilding that image,
and the new gate correctly blocked the release on it. `apt-get update && apt-get upgrade`/`apk
upgrade` pulls whatever's current in the distro's live package repos at build time, decoupled
from the base digest — standard practice for exactly this scenario, not a one-off patch.

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
├── postgres (PostgreSQL 18)
├── backend (FastAPI)
├── pgq-worker (PgQueuer, `pgq run app.tasks.pgq_app:main`)
└── frontend (Vite dev server, port 5173)
```

### Production (compose-prod.yaml)

```
compose-prod.yaml
├── postgres (PostgreSQL 18)             restart: unless-stopped
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

### Explicit compose project names — `compose.yaml` vs `compose-prod.yaml`

Both files pin a top-level `name:` (`pie-manager-dev` / `pie-manager`) instead of letting
`podman-compose`/`docker-compose` derive the project name from the containing directory's
basename. Without this, the dev checkout (`~/workspace/pie-manager`) and a real production
install (`~/.local/share/pie-manager`) resolve to the **same** project name ("pie-manager")
purely because both directories share that basename — meaning the same container names and
the same named volumes, even though the two compose files live at completely different paths.

**This is not theoretical — it happened.** A `podman-compose build`/`up` run from this dev
checkout in August 2026 (unreleased code including the migration for issue #123's "Performance
par secteur" feature) resolved to the same project as the live production install, ran
`alembic upgrade head` against the **real production Postgres volume**, and left it stamped
two migrations ahead of whatever image tag production's `.env` was actually pinned to. When
production's own containers next restarted on the old pinned image, the backend crash-looped
forever (`Can't locate revision`) — production was down until a real release (bundling the
unreleased migrations) was cut and installed. See git history around 2026-09-05 for the
incident; no data was lost (both migrations involved were additive/widening, not destructive),
but it could have gone the other way.

**Rule:** never remove either `name:` key. If a third throwaway compose stack is ever spun up
from a directory that could also end up named "pie-manager" (a clone, a copy, a test checkout),
give it an explicit `name:` too — don't rely on directory basenames staying distinct.

### Port selection (production)

Default port: **14943** (constant `defaultPort` in `installer/common.go`).

At install time, `findAvailablePort(14943)` scans from 14943 upward for the first free TCP port. The chosen port is written to `~/.local/share/pie-manager/.env` as `APP_PORT=<n>`. At subsequent starts, `runStart()` reads `APP_PORT` from `.env` and checks whether it is still free; if not, it picks a new port and rewrites `.env`.

The `.env` file also holds `APP_VERSION=<n>`. Both variables are consumed by `compose-prod.yaml` via `${APP_PORT:-14943}` and `${APP_VERSION:-dev}`.

## Database backup

- Endpoint `GET /api/admin/backup` → calls `pg_dump` via `subprocess` from the backend container
- Endpoint `POST /api/admin/restore` → `pg_restore --clean --if-exists --no-owner --no-privileges`
  — deliberately **no** `--single-transaction`: it would fail the whole restore on a
  non-critical `transaction_timeout` error emitted by dumps taken with a pg_dump newer than
  the target server (a documented pg_restore quirk, not something to "fix" by adding the flag back)
- Format `.dump` (custom binary pg_dump, compressed)
- `backend/Containerfile` pins `postgresql-client-18` to match the server (PostgreSQL 18) — a
  mismatched client version produces dumps the server's own pg_restore can't read, and an
  OLDER client outright refuses to dump a NEWER server at all

## PostgreSQL major-version bumps (16→18 done in #58 — template for any future bump)

**A PostgreSQL major-version bump is never a simple image-tag swap — never merge one via
Dependabot without redoing this whole exercise** (the `.github/dependabot.yml` `postgres`
ignore rule blocks the next major version specifically so this can't happen by accident).
Three independent problems, confirmed empirically (not just from docs) during #58, each
needing its own fix:

1. **Mount/PGDATA convention change.** `postgres:18-alpine`'s official image defaults
   `PGDATA` to a version-scoped subdirectory (`/var/lib/postgresql/18/docker`) under a new
   `/var/lib/postgresql` `VOLUME` — it refuses to start on a **fresh, empty** volume mounted
   the old way (`/var/lib/postgresql/data` directly), let alone an existing data volume. **Fix
   verified empirically, not just read from docs:** pinning `PGDATA: /var/lib/postgresql/data`
   explicitly in both compose files (a plain Postgres env var, honored regardless of the
   image's own new default) lets `postgres:18-alpine` start cleanly under the *exact same*
   mount layout `compose.yaml`/`compose-prod.yaml` already used for 16 — no volume
   restructuring needed at all. This trades away the new layout's own benefit (enabling
   `pg_upgrade --link` for a near-instant *future* major bump) in exchange for a much simpler
   *this* bump — a deliberate choice for a personal single-user app, revisit if that trade-off
   ever stops making sense.
2. **Client compatibility.** An older `pg_dump`/`pg_restore` client flatly refuses to touch a
   newer server (`aborting because of server version mismatch` — a hard PostgreSQL rule, not
   a bug) — `backend/Containerfile`'s pinned `postgresql-client-16` → `postgresql-client-18`
   bump above must happen in lockstep with the server bump, never independently.
3. **Existing installs.** Even with (1) fixed, a v18 binary still cannot read v16's on-disk
   catalog format — some data migration is mandatory. **`installer/common.go`'s
   `pgDataVolumeName`/`pgVersionMajor`/`composePostgresMajor`/`postgresMajorMismatch`
   implement a hard-stop guard**, wired into `install.go`/`install_darwin.go`'s upgrade path
   (Linux/macOS only — the old WSL2/Podman Windows installer this was never extended to has
   since been fully removed, issue #84; the native Windows launcher bundles fixed-version
   Postgres binaries rather than pulling an image tag, so this specific guard doesn't apply
   there the same way): before pulling any new image, it reads the existing volume's
   `PG_VERSION` file (found via `podman volume ls`, matched by a `_postgres_data` suffix —
   deliberately NOT reconstructing podman-compose's project-name-derivation algorithm from
   the install directory's basename, which differs across platforms/compose implementations
   and this project has never needed to pin down) via a throwaway read-only `alpine` reader
   that never starts postgres itself, and compares it against the target major version parsed
   directly out of the embedded `compose-prod.yaml`'s image tag. On a real mismatch, it prints
   step-by-step manual migration instructions (back up via the still-running old version's
   Administration système page, remove the old volume, re-run the installer fresh, restore)
   and exits **before** touching anything — never a blind image swap that would otherwise
   crash the new postgres container against old-format data with no warning.

**A full dump/restore round-trip was verified end-to-end with real production data** (not
just an empty schema): restore a real backup into a throwaway v16 container, `pg_dump` with
the v16 client, `pg_restore` into a throwaway v18 container (with the `PGDATA` fix) using the
v18 client bundled in `postgres:18-alpine` itself, then ran the real FastAPI backend directly
against the restored v18 database and confirmed the dashboard/transactions/portfolios
endpoints all computed correct figures from the real, restored data — not just that row
counts matched.

Treat any future postgres major bump (19+) as its own project repeating this same exercise
(mount/PGDATA compatibility check, client bump, installer guard re-verification, a real
dump/restore test against production-shaped data), never a routine dependency bump.

