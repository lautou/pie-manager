# Windows 11 test VM — reproducible setup

Scripts to recreate the libvirt/QEMU Windows 11 VM used to test the PIE Manager Windows
installer end-to-end, from a fresh Fedora host. Built from the actual working configuration
reached after extensive live debugging — the *why* behind each tuning choice is inlined as
comments directly in `01-create-vm.sh` (NOCOW disk placement, the specific CPU model) rather
than referenced externally, so this stays reproducible from a fresh clone alone. See also the
root repo's `.claude/rules/distribution.md` "Local win11 test VM" section for the higher-level
maintenance overview (script roles, the ISO-download mechanism's fragility caveat).

## Prerequisites

- Fedora with `virt-install`, `swtpm`, `genisoimage`, and the `virtio-win` package installed,
  libvirt/KVM set up, and your user in the `libvirt` group.
- A Windows 11 x64 ISO — see step 0 below to fetch it directly from Microsoft, no manual
  browser download needed.
- `sudo` access **only the very first time ever** on a given host (see step 1) — every
  subsequent rebuild needs no root at all.

## Steps

0. **`./00-download-win11-iso.py [--lang French] [--out win11.iso]`** — downloads the real,
   official Windows 11 multi-edition x64 ISO straight from Microsoft's own CDN, by replaying
   the same internal API calls the official download page's own JavaScript makes (session
   whitelisting + an anti-bot handshake, then the software-download-connector API for the
   real, time-limited link) — the same technique the well-known open-source tool
   [Fido](https://github.com/pbatard/Fido) uses, ported to plain Python (no dependencies
   beyond the standard library) since Fido's own command-line mode explicitly refuses to run
   on non-Windows platforms. If Microsoft changes this flow and the script starts failing,
   re-derive the current sequence from Fido's own up-to-date source rather than guessing.

1. **`./01-create-vm.sh <path-to-win11.iso>`** — creates the VM (NOCOW disk, correct CPU model,
   TPM 2.0, UEFI Secure Boot, guest-agent channel) and runs a **fully unattended** Windows
   install via `autounattend.xml` (issue #61): virtio driver injection, a local account instead
   of a Microsoft account, a silent `virtio-win-guest-tools` install, and an automatic shutdown
   once done — no GUI, no manual clicks. The script polls for that shutdown and returns once
   it happens (20-40+ minutes; several in-between reboots are normal). It's also fully
   idempotent: re-running it tears down any existing VM of the same name first, so "start over
   from scratch" is always just this one command. `sudo` is only required the first time ever
   on a host, to prepare the NOCOW disk directory — every rebuild after that runs unprivileged
   (libvirtd does the actual privileged work via its own socket).

2. **`./02-tune-and-snapshot.sh`** — applies the hyperv enlightenment set (fixes nested-Hyper-V
   crashes under KVM), verifies it landed, boots the VM, pushes and runs `tune-guest.ps1`
   (debloat + Defender exclusions + High Performance power plan), shuts down, and takes a
   `base-clean-tuned-<date>` snapshot — the reusable baseline for future installer test runs.
   This baseline has zero pre-trusted certificates and zero private keys (verified live via
   `Get-ChildItem Cert:\LocalMachine\Root, Cert:\LocalMachine\TrustedPublisher, Cert:\
   LocalMachine\My` — 18 stock Windows root CAs, nothing else) — a genuinely fresh Windows
   machine's state, not the "PIEManager cert + private key pre-imported" pollution issue #62
   found on an earlier, undocumented, manually-modified copy of this VM.

## Notes

- OneDrive disable in `tune-guest.ps1` uses the standard, well-known
  `DisableFileSyncNGSC` Group Policy method. This is **not verified** against whatever command
  was actually used originally (not recoverable from session history) — review before relying
  on it.
- `autounattend.xml`'s local-account bypass (`HideOnlineAccountScreens` +
  `UserAccounts/LocalAccounts`) was validated live on the French x64 multi-edition ISO fetched
  by step 0 — confirmed via `Get-LocalUser` showing only the `tester` account,
  `PrincipalSource: Local`. If a future Windows 11 build changes this behavior, re-validate the
  same way before assuming the answer file still works.
- Re-running `02-tune-and-snapshot.sh` is safe/idempotent (each edit no-ops if already applied)
  except for the snapshot itself, which always creates a new one — pass a different
  `SNAPSHOT_NAME` or delete the old one first if re-running.
