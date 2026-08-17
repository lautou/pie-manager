# Windows 11 test VM — reproducible setup

Scripts to recreate the libvirt/QEMU Windows 11 VM used to test the PIE Manager Windows
installer end-to-end, from a fresh Fedora host. Built from the actual working configuration
reached after extensive live debugging — the *why* behind each tuning choice is inlined as
comments directly in `01-create-vm.sh` (NOCOW disk placement, the specific CPU model) rather
than referenced externally, so this stays reproducible from a fresh clone alone. See also the
root repo's `.claude/rules/distribution.md` "Local win11 test VM" section for the higher-level
maintenance overview (script roles, the ISO-download mechanism's fragility caveat).

## Prerequisites

- Fedora with `virt-install`, `swtpm`, and the `virtio-win` package installed, libvirt/KVM set
  up, and your user in the `libvirt` group.
- A Windows 11 x64 ISO — see step 0 below to fetch it directly from Microsoft, no manual
  browser download needed.

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

1. **`sudo ./01-create-vm.sh <path-to-win11.iso>`** — creates the VM (NOCOW disk, correct CPU
   model, TPM 2.0, UEFI Secure Boot) and starts it ready for OS installation.

2. **Manual** — open `virt-manager` (or `virt-viewer win11`) and install Windows yourself:
   - The disk picker will be empty at first — click **"Load driver"**, browse the attached
     virtio-win CD, and load the driver from `viostor\w11\amd64` so the 64 GB disk appears.
   - At the network/account screen, to get a **local account** instead of a Microsoft account:
     open a command prompt with **Shift+F10**, run `start ms-cxh:localonly`, and continue —
     despite the window still saying "Microsoft account", this creates a local account form.
   - Finish OOBE, then run `virtio-win-guest-tools.exe` from the same attached CD — this
     installs the QXL/virtio drivers, `qemu-ga`, and the SPICE agent, all required for the
     guest-agent-driven automation this tooling assumes.
   - Shut down the VM once done.

3. **`./02-tune-and-snapshot.sh`** — applies the hyperv enlightenment set (fixes nested-Hyper-V
   crashes under KVM), verifies it landed, boots the VM, pushes and runs `tune-guest.ps1`
   (debloat + Defender exclusions + High Performance power plan), shuts down, and takes a
   `base-clean-tuned-<date>` snapshot — the reusable baseline for future installer test runs.

## Notes

- OneDrive disable in `tune-guest.ps1` uses the standard, well-known
  `DisableFileSyncNGSC` Group Policy method. This is **not verified** against whatever command
  was actually used originally (not recoverable from session history) — review before relying
  on it.
- Windows Setup and the local-account bypass are inherently GUI-driven and cannot be
  scripted — step 2 above is manual by design.
- Re-running `02-tune-and-snapshot.sh` is safe/idempotent (each edit no-ops if already applied)
  except for the snapshot itself, which always creates a new one — pass a different
  `SNAPSHOT_NAME` or delete the old one first if re-running.
