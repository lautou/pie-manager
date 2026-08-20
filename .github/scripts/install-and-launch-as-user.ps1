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

try {
    Add-AppxPackage -Path $MsixPath -Verbose

    $pkg = Get-AppxPackage -Name "PIEManager.PIEManager"
    if (-not $pkg) {
        "ERROR: Package not found after Add-AppxPackage" | Out-File -FilePath $ResultPath
        exit 1
    }
    $aumid = "$($pkg.PackageFamilyName)!App"

    Start-Process "explorer.exe" -ArgumentList "shell:AppsFolder\$aumid"
    "Installed and launched AUMID: $aumid" | Out-File -FilePath $ResultPath
} catch {
    "ERROR: $_" | Out-File -FilePath $ResultPath
    exit 1
}
