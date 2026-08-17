#!/bin/bash
# Creates the win11 test VM and runs a fully unattended Windows install via
# autounattend.xml (issue #61). Idempotent: re-running this script tears down
# any existing VM of the same name first, so "start over from scratch" is
# always just this one command. See README.md for the full workflow.
set -euo pipefail

ISO_PATH="${1:?Usage: $0 <path-to-win11.iso> [vm-name]}"
NAME="${2:-win11}"
DISK_DIR="/var/lib/libvirt/images/nocow"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$ISO_PATH" ]; then
  echo "ERROR: ISO not found: $ISO_PATH" >&2
  exit 1
fi

# qemu runs as the unprivileged 'qemu' user (dynamic_ownership, not the
# SELinux relabeling this was first assumed to use) — it needs 'x' (search)
# on EVERY directory between / and the ISO, not just the immediate parent
# (confirmed live: a home directory at mode 710 blocked this at the
# grandparent level even after fixing the immediate parent). Self-heal via
# ACL (needs no root: this only ever touches directories the invoking user
# already owns) instead of requiring a manual one-off fix per host.
if command -v setfacl >/dev/null 2>&1; then
  DIR="$(dirname "$(readlink -f "$ISO_PATH")")"
  while [ "$DIR" != "/" ]; do
    if ! getfacl -n "$DIR" 2>/dev/null | grep -q "^user:qemu:..x$" \
       && ! stat -c '%A' "$DIR" | cut -c8-10 | grep -q "..x"; then
      echo "==> Granting the 'qemu' user search access to $DIR"
      setfacl -m u:qemu:x "$DIR"
    fi
    DIR="$(dirname "$DIR")"
  done
else
  echo "WARNING: 'setfacl' not found — if virt-install fails with a permission error reading" >&2
  echo "the ISO, grant search access to every directory in its path manually: setfacl -m u:qemu:x <dir>" >&2
fi

# Root is only genuinely required the first time ever on a given host, to
# mkdir/chattr the NOCOW disk directory (a plain filesystem write under
# /var/lib/libvirt/images, which libvirtd does NOT do on our behalf). Once
# that directory exists with NOCOW already set, every actual privileged
# operation (disk creation, domain define/start) goes through libvirtd's own
# socket instead, which this host's polkit config already allows for an
# unprivileged member of the libvirt group — so re-running to rebuild the VM
# from scratch does not need sudo again.
if [ "$EUID" -ne 0 ]; then
  if [ -d "$DISK_DIR" ] && lsattr -d "$DISK_DIR" 2>/dev/null | grep -q 'C'; then
    echo "NOTE: not running as root — '$DISK_DIR' already exists with NOCOW (+C) set, skipping that one-time setup step."
  else
    echo "ERROR: must run as root the first time (needs to mkdir/chattr under /var/lib/libvirt/images)." >&2
    echo "Re-run with: sudo $0 $*" >&2
    exit 1
  fi
fi

if [ "$EUID" -eq 0 ]; then
  # NOCOW must be set on the directory BEFORE the disk file exists — it does
  # not apply retroactively. btrfs COW + qcow2's own COW is a severe I/O
  # amplifier for VM disk images (double copy-on-write on the same small
  # random writes a VM disk produces) - roughly halved guest-agent-ready boot
  # time once fixed.
  mkdir -p "$DISK_DIR"
  chattr +C "$DISK_DIR" 2>/dev/null || true # no-op if already set, or not on btrfs
fi

if virsh --connect qemu:///system dominfo "$NAME" >/dev/null 2>&1; then
  echo "==> Existing domain '$NAME' found — tearing down for a fresh rebuild"
  virsh --connect qemu:///system destroy "$NAME" >/dev/null 2>&1 || true
  # Deliberately NOT --remove-all-storage: that flag deletes every disk
  # attached to the domain, including the shared virtio-win driver ISO
  # (a pooled system resource this VM merely attaches read-only, not
  # something it owns) — confirmed the hard way, it silently deleted
  # /usr/share/virtio-win/virtio-win.iso (an RPM-owned symlink) on a first
  # version of this script. Only the VM's own qcow2 volume is ours to delete.
  virsh --connect qemu:///system undefine "$NAME" --nvram --snapshots-metadata
  virsh --connect qemu:///system vol-delete --pool nocow "$NAME.qcow2" 2>/dev/null || true
fi

# The answer-file ISO is a generated build artifact (from the checked-in
# autounattend.xml template), not something to commit — build it fresh under
# /tmp on every run, in a path this user owns outright, since
# /var/lib/libvirt/images itself is root-owned and not writable by a plain
# genisoimage invocation (unlike disk creation, this is a direct filesystem
# write, not routed through libvirtd). libvirt dynamically relabels any
# readable file referenced as a domain disk at start time, so a /tmp path
# works exactly like the win11 ISO already living under ~/Downloads does.
ANSWER_ISO="$(mktemp --suffix=.iso)"
ANSWER_SRC_DIR="$(mktemp -d)"
# libvirtd's dynamic_ownership may chown $ANSWER_ISO to the 'qemu' user once
# the domain starts (to let the unprivileged qemu process read it) — on a
# sticky-bit dir like /tmp that means our own `rm` can no longer remove it.
# Harmless either way (tiny generated file, OS reclaims /tmp eventually), so
# tolerate cleanup failure rather than letting it mask the script's real exit code.
trap 'rm -f "$ANSWER_ISO" 2>/dev/null || true; rm -rf "$ANSWER_SRC_DIR" 2>/dev/null || true' EXIT
cp "$SCRIPT_DIR/autounattend.xml" "$ANSWER_SRC_DIR/autounattend.xml"
genisoimage -quiet -o "$ANSWER_ISO" -V "AUTOUNATTEND" -J -R "$ANSWER_SRC_DIR"

# A named, curated CPU model below (not host-passthrough/host-model) with
# +vmx/+invtsc forced on: this guest runs a nested hypervisor (WSL2/Podman
# Machine), and host-passthrough's full real CPUID surface reproducibly
# crashed the nested hypervisor on first boot (Windows bugcheck 0x00020001)
# regardless of core topology or added hv-* enlightenment flags - confirmed
# by elimination across 4 configurations. This model swap is what actually
# fixed it.
virt-install \
  --connect qemu:///system \
  --name "$NAME" \
  --memory 8192 \
  --vcpus 4 \
  --cpu Skylake-Client-v4,+vmx,+invtsc,-hypervisor \
  --machine q35 \
  --os-variant win11 \
  --disk "path=$DISK_DIR/$NAME.qcow2,size=64,bus=virtio,cache=none,io=native,discard=unmap,boot.order=2" \
  --disk "path=$ISO_PATH,device=cdrom,boot.order=1" \
  --disk "vol=virtio-win/virtio-win.iso,device=cdrom" \
  --disk "path=$ANSWER_ISO,device=cdrom" \
  --network network=default,model=virtio \
  --graphics spice \
  --channel unix,target_type=virtio,name=org.qemu.guest_agent.0 \
  --video qxl \
  --tpm backend.type=emulator,backend.version=2.0,model=tpm-crb \
  --boot firmware=efi,firmware.feature0.name=secure-boot,firmware.feature0.enabled=yes \
  --features smm.state=on \
  --noautoconsole

# Microsoft's own bootmgfw.efi always shows an interactive "Press any key to
# boot from CD or DVD......" prompt when booting from optical media, with a
# short (a few seconds, not the ~5s it appears to advertise) timeout — miss
# it and OVMF falls through to the blank system disk, finds nothing bootable,
# and drops into its own interactive Boot Manager Menu instead. A single
# well-timed keypress is unreliable (confirmed live: a screenshot-then-react
# loop missed the window twice in a row), so spam ENTER for a generous
# window right after the domain starts instead of trying to time one keypress.
echo "==> Nudging past the interactive 'press any key to boot from CD' EFI prompt"
for _ in $(seq 1 60); do
  virsh --connect qemu:///system send-key "$NAME" KEY_ENTER >/dev/null 2>&1 || true
  sleep 0.5
done

echo "==> VM '$NAME' created, booting into the fully unattended Windows install."
echo "    Waiting for autounattend.xml + guest-tools install + auto-shutdown"
echo "    (this can take 20-40+ minutes; several in-between reboots are normal)..."

TIMEOUT_S=$((60 * 60))
ELAPSED=0
while true; do
  state=$(virsh --connect qemu:///system domstate "$NAME" 2>/dev/null || echo "unknown")
  if [ "$state" = "shut off" ]; then
    echo "OK: '$NAME' shut down on its own — unattended install complete."
    break
  fi
  if [ "$ELAPSED" -ge "$TIMEOUT_S" ]; then
    echo "ERROR: '$NAME' did not shut down within $((TIMEOUT_S / 60)) minutes (state: $state)." >&2
    echo "Inspect with: virt-viewer $NAME  (or: virsh --connect qemu:///system dumpxml $NAME)" >&2
    exit 1
  fi
  sleep 30
  ELAPSED=$((ELAPSED + 30))
  if [ $((ELAPSED % 300)) -eq 0 ]; then
    echo "   ...still waiting (${ELAPSED}s elapsed, state: $state)"
  fi
done

cat <<EOF

VM '$NAME' installed and shut down automatically (autounattend.xml — issue #61).
Next: ./02-tune-and-snapshot.sh
EOF
