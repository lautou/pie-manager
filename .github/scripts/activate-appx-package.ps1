# Activates an installed AppX/MSIX package by AUMID, under THIS process's own token rather than
# whatever token an already-running Explorer shell process happens to have.
#
# Why this exists: launching via a fresh "explorer.exe shell:AppsFolder\<aumid>" invocation does
# NOT reliably run the target app under the CALLING process's own token. Explorer is
# single-instance per session — a fresh invocation typically just forwards the activation
# request via COM to the already-running Explorer process and exits; the actual app spawn
# happens inside that pre-existing process, under ITS token, not the caller's. This defeats any
# attempt to launch a full-trust MSIX app with a deliberately different (e.g. de-elevated) token
# than whatever Explorer's own long-lived process already has.
#
# A prior attempt called IApplicationActivationManager.ActivateApplication directly via COM
# interop to sidestep Explorer entirely. That hit a genuine, unresolved COM-level failure
# ("incorrect format", 0x8007000B) three interop layers deep (QueryInterface cast, apartment
# state, and finally the call itself) with no further progress — abandoned in favor of this
# simpler, more direct fix: kill the existing Explorer process immediately before launching, so
# there is no pre-existing instance left to delegate to. The fresh "explorer.exe
# shell:AppsFolder\..." invocation this script then makes has no choice but to become the
# session's primary shell handler itself, actually performing the launch under THIS process's
# own token (inherited from whatever ran this script — e.g. a Scheduled Task with a specific
# run level).
#
# See build-installer.yml's package-native-launcher-msix job and issue #116 for the concrete
# problem this was built to diagnose/fix (postgres.exe refusing to start under an elevated
# token on GitHub Actions' windows-latest runner).

param(
    [Parameter(Mandatory = $true)]
    [string]$Aumid,

    [Parameter(Mandatory = $true)]
    [string]$ResultPath
)

try {
    Get-Process -Name explorer -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 500

    Start-Process "explorer.exe" -ArgumentList "shell:AppsFolder\$Aumid"
    "Launched via explorer.exe after killing any pre-existing instance" | Out-File -FilePath $ResultPath
} catch {
    "ERROR: $_" | Out-File -FilePath $ResultPath
    exit 1
}
