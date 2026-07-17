# Guest-side debloat + tuning for the win11 PIE Manager installer test VM.
# Run once, elevated, after Windows Setup + virtio-win-guest-tools are done.
# Consolidates debloat.ps1/debloat2.ps1 from earlier session history plus the
# Defender/power-plan tuning established during the WSL2 installer investigation.
$ErrorActionPreference = 'SilentlyContinue'
$report = @()

function Disable-SvcSafe($name) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($svc) {
        Stop-Service -Name $name -Force -ErrorAction SilentlyContinue
        Set-Service -Name $name -StartupType Disabled -ErrorAction SilentlyContinue
        return "disabled: $name"
    }
    return "absent: $name"
}

foreach ($s in 'SysMain', 'DiagTrack', 'WSearch', 'XblAuthManager', 'XblGameSave', 'XboxNetApiSvc', 'XboxGipSvc') {
    $report += Disable-SvcSafe $s
}

# --- AppX bloat removal ---
$pkgs = @(
    'MicrosoftWindows.Client.WebExperience', # Widgets
    'Microsoft.XboxGamingOverlay',
    'Microsoft.GamingApp',
    'Microsoft.XboxIdentityProvider',
    'Microsoft.XboxSpeechToTextOverlay',
    'Microsoft.549981C3F5F10', # Xbox app family
    'Microsoft.BingNews',
    'Microsoft.BingWeather',
    'Microsoft.ZuneMusic',
    'Microsoft.ZuneVideo',
    'Microsoft.YourPhone' # Phone Link
)
foreach ($p in $pkgs) {
    $found = Get-AppxPackage -AllUsers -Name $p -ErrorAction SilentlyContinue
    if ($found) {
        $found | Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue
        $report += "removed appx: $p"
    }
    else {
        $report += "absent appx: $p"
    }
}

# --- GameDVR / Widgets policy ---
New-Item -Path 'HKCU:\System\GameConfigStore' -Force | Out-Null
Set-ItemProperty -Path 'HKCU:\System\GameConfigStore' -Name 'GameDVR_Enabled' -Value 0 -Type DWord -Force
New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\GameDVR' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\GameDVR' -Name 'AllowGameDVR' -Value 0 -Type DWord -Force
$report += "GameDVR disabled"

New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Dsh' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Dsh' -Name 'AllowNewsAndInterests' -Value 0 -Type DWord -Force
$report += "Widgets policy disabled"

# --- Delivery Optimization / background apps ---
New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization' -Name 'DODownloadMode' -Value 0 -Type DWord -Force
$report += "Delivery Optimization: HTTP only (P2P off)"

New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\AppPrivacy' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\AppPrivacy' -Name 'LetAppsRunInBackground' -Value 2 -Type DWord -Force
$report += "Background apps: denied globally"

# --- OneDrive: standard method, NOT verified against what was originally used ---
# (mentioned as done in an earlier snapshot's description, but the exact command
# used wasn't recoverable from session history — review before relying on this)
New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\OneDrive' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\OneDrive' -Name 'DisableFileSyncNGSC' -Value 1 -Type DWord -Force
$report += "OneDrive sync disabled (best-effort, unverified method)"

# --- Telemetry/CEIP scheduled tasks ---
$tasks = @(
    @{Path = '\Microsoft\Windows\Application Experience\'; Name = 'Microsoft Compatibility Appraiser' },
    @{Path = '\Microsoft\Windows\Application Experience\'; Name = 'ProgramDataUpdater' },
    @{Path = '\Microsoft\Windows\Customer Experience Improvement Program\'; Name = 'Consolidator' },
    @{Path = '\Microsoft\Windows\Customer Experience Improvement Program\'; Name = 'UsbCeip' },
    @{Path = '\Microsoft\Windows\DiskDiagnostic\'; Name = 'Microsoft-Windows-DiskDiagnosticDataCollector' }
)
foreach ($t in $tasks) {
    $task = Get-ScheduledTask -TaskPath $t.Path -TaskName $t.Name -ErrorAction SilentlyContinue
    if ($task) {
        Disable-ScheduledTask -TaskPath $t.Path -TaskName $t.Name -ErrorAction SilentlyContinue | Out-Null
        $report += "task disabled: $($t.Name)"
    }
}

# --- Per-user tuning (targets the interactive user's hive by SID, since this ---
# --- runs via guest-exec as SYSTEM and HKCU would otherwise be the wrong hive) ---
$sid = (New-Object System.Security.Principal.NTAccount('pie')).Translate([System.Security.Principal.SecurityIdentifier]).Value
$userHive = "Registry::HKEY_USERS\$sid"
if (-not (Test-Path $userHive)) {
    $report += "WARNING: user hive not mounted - HKCU-scoped settings skipped"
}
else {
    $cdmPath = "$userHive\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
    New-Item -Path $cdmPath -Force | Out-Null
    foreach ($name in 'SubscribedContent-338388Enabled', 'SubscribedContent-338389Enabled', 'SubscribedContent-353694Enabled', 'SubscribedContent-353696Enabled', 'SilentInstalledAppsEnabled', 'SystemPaneSuggestionsEnabled', 'ContentDeliveryAllowed', 'OemPreInstalledAppsEnabled', 'PreInstalledAppsEnabled', 'PreInstalledAppsEverEnabled') {
        Set-ItemProperty -Path $cdmPath -Name $name -Value 0 -Type DWord -Force
    }
    $report += "Start suggestions / sponsored content: disabled"

    $vfxPath = "$userHive\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects"
    New-Item -Path $vfxPath -Force | Out-Null
    Set-ItemProperty -Path $vfxPath -Name 'VisualFXSetting' -Value 2 -Type DWord -Force
    Set-ItemProperty -Path "$userHive\Control Panel\Desktop" -Name 'UserPreferencesMask' -Value ([byte[]](0x90, 0x12, 0x03, 0x80, 0x10, 0x00, 0x00, 0x00)) -Type Binary -Force
    Set-ItemProperty -Path "$userHive\Control Panel\Desktop" -Name 'DragFullWindows' -Value '0' -Force
    New-Item -Path "$userHive\Control Panel\Desktop\WindowMetrics" -Force | Out-Null
    Set-ItemProperty -Path "$userHive\Control Panel\Desktop\WindowMetrics" -Name 'MinAnimate' -Value '0' -Force
    New-Item -Path "$userHive\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" -Force | Out-Null
    Set-ItemProperty -Path "$userHive\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" -Name 'TaskbarAnimations' -Value 0 -Type DWord -Force
    New-Item -Path "$userHive\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" -Force | Out-Null
    Set-ItemProperty -Path "$userHive\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" -Name 'EnableTransparency' -Value 0 -Type DWord -Force
    $report += "Visual effects: best performance (animations/transparency off)"
}

# --- Power plan: High Performance (well-known static GUID) ---
powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
$report += "power plan: High Performance"

# --- Defender exclusions for WSL2/Podman (avoid real-time scan overhead on ---
# --- the exact I/O path the PIE Manager installer exercises) ---
$wslVhdxPaths = Get-ChildItem "$env:LOCALAPPDATA\Packages" -Filter '*WSL*' -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
$exclusionPaths = @(
    "$env:LOCALAPPDATA\containers",
    "$env:USERPROFILE\.local\share\containers"
) + $wslVhdxPaths
Add-MpPreference -ExclusionPath $exclusionPaths -ErrorAction SilentlyContinue
Add-MpPreference -ExclusionProcess 'vmmem', 'vmmemWSL', 'wslhost.exe', 'podman.exe', 'wsl.exe', 'docker-compose.exe' -ErrorAction SilentlyContinue
$report += "Defender exclusions added for WSL2/Podman paths and processes"

$report -join "`n"
