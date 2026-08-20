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

    # Deliberately NOT "explorer.exe shell:AppsFolder\<aumid>" (tried and confirmed not to
    # work, even combined with a genuinely non-admin user, SeInteractiveLogonRight, and PsExec
    # -i for real desktop access). AppX/MSIX activation via shell:AppsFolder routes through
    # explorer.exe + the Application Activation Manager COM broker, which depends on
    # interactive-session infrastructure (the AppInfo service, RuntimeBroker, per-session COM
    # launch permissions) that no programmatically-created session fully replicates — a
    # widely-documented class of problem, not specific to this app or this fix attempt (see
    # e.g. github.com/openai/codex#25221, a near-identical symptom: shell:AppsFolder activation
    # silently doing nothing/launching the wrong thing, with the same documented workaround).
    #
    # launcher-native.exe is a full-trust MSIX app (not sandboxed/AppContainer), so once
    # installed it's a completely ordinary Win32 executable at a real file path — bypassing
    # AppsFolder activation and launching that path directly sidesteps the entire broken
    # broker/COM activation chain, since a full-trust package doesn't need it to run and this
    # app calls no WinRT/Windows.ApplicationModel APIs that would need activation-provided
    # package identity context.
    $exePath = Join-Path $pkg.InstallLocation "launcher-native.exe"
    if (-not (Test-Path $exePath)) {
        "ERROR: launcher-native.exe not found at $exePath" | Out-File -FilePath $ResultPath
        exit 1
    }

    Start-Process $exePath
    "Installed and launched directly: $exePath" | Out-File -FilePath $ResultPath
} catch {
    "ERROR: $_" | Out-File -FilePath $ResultPath
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
