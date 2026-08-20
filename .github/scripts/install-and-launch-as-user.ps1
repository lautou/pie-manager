# Installs and launches the native launcher MSIX as whichever user runs this script — meant to
# be invoked via Start-Process -Credential as a genuinely non-administrator local test user (see
# build-installer.yml's package-native-launcher-msix job and issue #116).
#
# Why both steps happen here, as this user, rather than installing once (as the elevated CI
# session) and only launching as this user: Add-AppxPackage has no -AllUsers switch (that
# parameter exists on Get-AppxPackage/Remove-AppxPackage, not Add-AppxPackage) — a package
# installed by one user is only visible to that same user. The signing certificate is already
# trusted into Cert:\LocalMachine\TrustedPeople by an earlier step (a machine-wide store, visible
# to every user), so this user's own Add-AppxPackage call can validate the signature without any
# extra per-user trust setup. This also matches how a real end user actually experiences the
# app: they install AND run it under their own, ordinary non-admin account — there's no separate
# "provision for everyone" step in real usage either.

param(
    [Parameter(Mandatory = $true)]
    [string]$MsixPath,

    [Parameter(Mandatory = $true)]
    [string]$ResultPath
)

# Start-Process -Credential (the only way to launch this script as a different user while still
# attached to the current interactive desktop) cannot be combined with
# -RedirectStandardOutput/-RedirectStandardError at all — PowerShell rejects that parameter
# combination outright. Start-Transcript, called from INSIDE this script instead, captures
# everything regardless of how the script was launched — the only way to get real visibility
# into what happens in this process once Start-Process hands off to it.
$transcriptPath = "C:\Windows\Temp\install-and-launch-transcript.log"
Start-Transcript -Path $transcriptPath -Force | Out-Null

# Written unconditionally, before anything else that could fail, so a run that never gets this
# far (e.g. the script itself couldn't be read, or never even started) is distinguishable from
# one that started but failed inside the try/catch below.
"STARTED as $(whoami)" | Out-File -FilePath $ResultPath

try {
    Add-AppxPackage -Path $MsixPath -Verbose

    $pkg = Get-AppxPackage -Name "PIEManager.PIEManager"
    if (-not $pkg) {
        "ERROR: Package not found after Add-AppxPackage" | Out-File -FilePath $ResultPath
        exit 1
    }
    $aumid = "$($pkg.PackageFamilyName)!App"

    # Start-Process -Credential attaches this process to the SAME window station/desktop as the
    # calling (elevated, runneradmin) session, rather than creating a fully separate one — so
    # the elevated session's own pre-existing explorer.exe is still present on that shared
    # window station. Explorer's single-instance-per-session model appears to key off the window
    # station, not the account: confirmed live, a fresh "explorer.exe shell:AppsFolder\..."
    # invocation here did not launch anything at all (no launcher-native.exe process ever
    # appeared) — almost certainly because it delegated to that pre-existing instance the same
    # way it did earlier when both invocations belonged to the same (elevated) account. Killing
    # it first — same fix already proven necessary once before — removes it so THIS invocation
    # has no instance left to delegate to, under this user's own (genuinely non-admin) token.
    Get-Process -Name explorer -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 500

    Start-Process "explorer.exe" -ArgumentList "shell:AppsFolder\$aumid"
    "Installed and launched AUMID: $aumid" | Out-File -FilePath $ResultPath
} catch {
    "ERROR: $_" | Out-File -FilePath $ResultPath
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
