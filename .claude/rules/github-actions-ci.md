---
paths:
  - ".github/workflows/*.yml"
  - ".github/dependabot.yml"
---

### GitHub Actions annotations
Pinned versions are the Node.js 24-native ones (verified via each action's own `action.yml`,
`using: node24`): `checkout@v6.0.2`, `setup-node@v6.4.0`, `setup-python@v6.2.0`,
`upload-artifact@v7.0.1`, `download-artifact@v8.0.1`.

### Never chain more than 2 commands with `&&` in a workflow `run:` block

Under GitHub Actions' default `set -e`, a failing command that is **not the last** member of
an AND-OR list (`cmd1 && cmd2 && cmd3`) is silently exempt from triggering errexit (POSIX
rule) — the step reports success even though `cmd1`/`cmd2` genuinely failed. Confirmed live:
`cd installer && go mod tidy && go vet ./... && go test ./... && CGO_ENABLED=0 go build ./...`
in `ci.yml` let a real `go test` **failure** (`FAIL`, non-zero exit) print to the log while the
step still reported success — this exact line had been in CI since early in the project,
meaning a real installer test failure could have gone unnoticed the whole time. Fix: put each
command on its own line (a bare simple command IS correctly caught by `set -e`) instead of
chaining with `&&`. A 2-command chain where only the trailing command's failure matters
(`sudo apt-get update && sudo apt-get install -y X`, tolerating a stale-but-working package
cache) is fine to leave as-is — the risk is specifically chains of 3+ commands, or any chain
where a *non-final* command's failure is the one that actually needs to fail the step.

### GitHub Actions artifact quota
`publish-images.yml` does **not** use GitHub Actions artifacts at all — it pushes container
images straight to Quay.io, a separate registry with its own storage, not this quota. The
actual GitHub artifact consumers, both already `retention-days: 1`:
- `ci.yml` backend coverage upload, `continue-on-error: true`
- `build-installer.yml`'s 3 binary uploads (Linux/Windows/macOS), used to hand binaries off to
  the per-platform install-test jobs and for real-hardware testing
- If quota exceeded: `gh api repos/lautou/pie-manager/actions/artifacts --paginate | python3 -c "..."` to list/delete

### Mandatory cleanup when deleting a tag/release
When deleting tags/releases (cleanup), always do all 3 actions:
1. `gh release delete vX.Y.Z --yes` — delete the GitHub release
2. `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z` — delete the tag
3. Quay.io images: delete manually via Quay.io UI (no automatic cleanup configured)
   Registry: `quay.io/ltourreau/pie-manager-backend` and `quay.io/ltourreau/pie-manager-frontend`

