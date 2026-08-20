# Activates an installed AppX/MSIX package by AUMID via the IApplicationActivationManager COM
# interface directly, bypassing explorer.exe's shell:AppsFolder handling entirely.
#
# Why this exists: launching via "explorer.exe shell:AppsFolder\<aumid>" does NOT reliably run
# the target app under the CALLING process's own token. Explorer is single-instance per
# session — a fresh "explorer.exe shell:AppsFolder\..." invocation typically just forwards the
# activation request via COM to the already-running Explorer process and exits; the actual app
# spawn happens inside that pre-existing process, under ITS token, not the caller's. This
# defeats any attempt to launch a full-trust MSIX app with a deliberately different
# (e.g. de-elevated) token than whatever Explorer's own long-lived process already has.
#
# Calling ActivateApplication directly from THIS process makes this process itself responsible
# for the spawn, so the launched app inherits this process's own token — the behavior actually
# needed when this script is run from inside e.g. a Scheduled Task with a specific run level.
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

# The coclass declares it implements the interface directly (rather than getting a raw
# __ComObject via GetTypeFromCLSID+Activator.CreateInstance and casting it afterward with `-as`)
# — confirmed live this matters: the cast-based approach's runtime QueryInterface failed under
# PowerShell 7 (.NET, not .NET Framework), even though the identical shape of code is a commonly
# published pattern for classic Windows PowerShell 5.1. Declaring the interface directly on the
# class lets normal COM activation (CoCreateInstance, triggered by `New-Object`) wire up the
# vtable dispatch from the start, without a separate runtime cast step.
Add-Type @"
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("2e941141-7f97-4756-ba1d-9decde894a3d"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IApplicationActivationManager
{
    [PreserveSig]
    int ActivateApplication(
        [MarshalAs(UnmanagedType.LPWStr)] string appUserModelId,
        [MarshalAs(UnmanagedType.LPWStr)] string arguments,
        int options,
        out uint processId);
}

[ComImport, Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")]
public class ApplicationActivationManager : IApplicationActivationManager
{
    [PreserveSig]
    public extern int ActivateApplication(
        [MarshalAs(UnmanagedType.LPWStr)] string appUserModelId,
        [MarshalAs(UnmanagedType.LPWStr)] string arguments,
        int options,
        out uint processId);
}
"@

try {
    $aam = New-Object ApplicationActivationManager

    [uint32]$processId = 0
    $hr = $aam.ActivateApplication($Aumid, "", 0, [ref]$processId)
    "HRESULT=0x$($hr.ToString('X8')) ProcessId=$processId" | Out-File -FilePath $ResultPath
} catch {
    "ERROR: $_" | Out-File -FilePath $ResultPath
    exit 1
}
