#!/bin/bash
# Applies CPU/hyperv tuning, runs guest-side debloat, verifies, and snapshots
# the win11 test VM as the reusable baseline. Run after Windows Setup +
# virtio-win-guest-tools are done and the VM is shut off. See README.md.
set -euo pipefail

NAME="${1:-win11}"
SNAPSHOT_NAME="${2:-base-clean-tuned-$(date +%F)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

state=$(virsh --connect qemu:///system domstate "$NAME")
if [ "$state" != "shut off" ]; then
  echo "ERROR: '$NAME' must be shut off first (current state: $state)." >&2
  echo "Finish Windows Setup + virtio-win-guest-tools, then shut down and re-run." >&2
  exit 1
fi

echo "==> Applying hyperv enlightenment set (fixes nested-Hyper-V crashes under KVM)"
virt-xml --connect qemu:///system "$NAME" --edit --features \
  hyperv.relaxed.state=on,hyperv.vapic.state=on,hyperv.spinlocks.state=on,hyperv.spinlocks.retries=8191,hyperv.vpindex.state=on,hyperv.runtime.state=on,hyperv.synic.state=on,hyperv.stimer.state=on,hyperv.reset.state=on,hyperv.frequencies.state=on,hyperv.reenlightenment.state=on,hyperv.tlbflush.state=on,hyperv.ipi.state=on,hyperv.evmcs.state=on,hyperv.emsr_bitmap.state=on

echo "==> Verifying tuning landed"
XML=$(virsh --connect qemu:///system dumpxml "$NAME")
FAIL=0
echo "$XML" | grep -q "Skylake-Client-v4" || { echo "MISSING: CPU model"; FAIL=1; }
echo "$XML" | grep -q "<relaxed state='on'/>" || { echo "MISSING: hyperv relaxed"; FAIL=1; }
echo "$XML" | grep -q "cache='none'" || { echo "MISSING: disk cache=none"; FAIL=1; }
echo "$XML" | grep -q "io='native'" || { echo "MISSING: disk io=native"; FAIL=1; }
if [ "$FAIL" -eq 1 ]; then
  echo "ERROR: one or more expected settings did not apply (silent no-op) — inspect 'virsh dumpxml $NAME'." >&2
  exit 1
fi
echo "OK: CPU model, hyperv flags, and disk cache/io all confirmed in the domain XML."

echo "==> Booting VM to run guest-side debloat/tuning"
virsh --connect qemu:///system start "$NAME"

for _ in $(seq 1 30); do
  if virsh --connect qemu:///system qemu-agent-command "$NAME" '{"execute":"guest-ping"}' >/dev/null 2>&1; then
    break
  fi
  sleep 10
done

python3 - "$NAME" "$SCRIPT_DIR/tune-guest.ps1" <<'PYEOF'
import base64, json, subprocess, sys, time

name, script_path = sys.argv[1], sys.argv[2]

def qga(cmd, timeout=30):
    r = subprocess.run(
        ["virsh", "--connect", "qemu:///system", "qemu-agent-command", name, json.dumps(cmd)],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.stdout.strip(), r.stderr.strip()

with open(script_path, encoding="utf-8") as f:
    script = f.read()
b64 = base64.b64encode(script.encode("utf-16-le")).decode("ascii")

out, err = qga({
    "execute": "guest-exec",
    "arguments": {
        "path": "powershell.exe",
        "arg": ["-NoProfile", "-NonInteractive", "-EncodedCommand", b64],
        "capture-output": True,
    },
}, timeout=30)
if not out:
    print(f"ERROR: guest-exec dispatch failed: {err}", file=sys.stderr)
    sys.exit(1)
pid = json.loads(out)["return"]["pid"]

for _ in range(30):
    time.sleep(2)
    out, err = qga({"execute": "guest-exec-status", "arguments": {"pid": pid}})
    if not out:
        continue
    status = json.loads(out)["return"]
    if status.get("exited"):
        print(f"tune-guest.ps1 exit code: {status.get('exitcode')}")
        if "out-data" in status:
            print(base64.b64decode(status["out-data"]).decode(errors="replace"))
        if status.get("exitcode") != 0:
            sys.exit(1)
        break
else:
    print("ERROR: tune-guest.ps1 timed out", file=sys.stderr)
    sys.exit(1)
PYEOF

echo "==> Shutting down"
virsh --connect qemu:///system shutdown "$NAME"
for _ in $(seq 1 30); do
  state=$(virsh --connect qemu:///system domstate "$NAME")
  [ "$state" = "shut off" ] && break
  sleep 5
done

echo "==> Snapshotting as '$SNAPSHOT_NAME'"
virsh --connect qemu:///system snapshot-create-as "$NAME" "$SNAPSHOT_NAME" \
  "CPU/hyperv/disk tuning + guest debloat applied, verified via dumpxml"

echo "Done. '$SNAPSHOT_NAME' is the reusable baseline for future installer test runs."
