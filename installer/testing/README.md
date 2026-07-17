# Windows 11 test VM — reproducible setup

Scripts to recreate the libvirt/QEMU Windows 11 VM used to test the PIE Manager Windows
installer end-to-end, from a fresh Fedora host. Built from the actual working configuration
reached after extensive live debugging (see the global `CLAUDE.md`'s "libvirt/QEMU VM
investigation and automation" section for the *why* behind each tuning choice below — this
README won't repeat it).

## Prerequisites

- Fedora with `virt-install`, `swtpm`, and the `virtio-win` package installed, libvirt/KVM set
  up, and your user in the `libvirt` group.
- A Windows 11 ISO downloaded manually (licensing — not scriptable).

## Steps

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
