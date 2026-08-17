#!/bin/bash
# Creates the win11 test VM ready for interactive Windows installation.
# See README.md for the full workflow and prerequisites.
set -euo pipefail

ISO_PATH="${1:?Usage: $0 <path-to-win11.iso> [vm-name]}"
NAME="${2:-win11}"
DISK_DIR="/var/lib/libvirt/images/nocow"

if [ ! -f "$ISO_PATH" ]; then
  echo "ERROR: ISO not found: $ISO_PATH" >&2
  exit 1
fi

if [ "$EUID" -ne 0 ]; then
  echo "ERROR: must run as root (needs to mkdir/chattr under /var/lib/libvirt/images)." >&2
  echo "Re-run with: sudo $0 $*" >&2
  exit 1
fi

# NOCOW must be set on the directory BEFORE the disk file exists — it does not
# apply retroactively. btrfs COW + qcow2's own COW is a severe I/O amplifier
# for VM disk images (double copy-on-write on the same small random writes a
# VM disk produces) - roughly halved guest-agent-ready boot time once fixed.
mkdir -p "$DISK_DIR"
chattr +C "$DISK_DIR" 2>/dev/null || true # no-op if already set, or not on btrfs

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
  --disk "path=$DISK_DIR/$NAME.qcow2,size=64,bus=virtio,cache=none,io=native,discard=unmap" \
  --disk "path=$ISO_PATH,device=cdrom" \
  --disk "pool=virtio-win,vol=virtio-win.iso,device=cdrom" \
  --network network=default,model=virtio \
  --graphics spice \
  --video qxl \
  --tpm backend.type=emulator,backend.version=2.0,model=tpm-crb \
  --boot firmware=efi,firmware.feature0.name=secure-boot,firmware.feature0.enabled=yes \
  --features smm.state=on \
  --noautoconsole

cat <<EOF

VM '$NAME' created and booting from the Windows 11 ISO.

Next (manual, see README.md for details):
  1. Open virt-manager (or: virt-viewer $NAME) and install Windows.
     - Disk picker will be empty: "Load driver" -> virtio-win CD -> viostor\\w11\\amd64
     - At the account screen: Shift+F10 -> 'start ms-cxh:localonly' for a local account
  2. Run virtio-win-guest-tools.exe from the attached virtio-win CD.
  3. Shut down the VM.
  4. Run: ./02-tune-and-snapshot.sh
EOF
