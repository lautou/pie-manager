# Grants a Windows local security "user right" (e.g. SeInteractiveLogonRight, "Allow log on
# locally") to a local account via the LSA policy API — there is no built-in PowerShell cmdlet
# for this. Needed because GitHub Actions' windows-latest runner is built on a Windows Server
# base image; Windows Server images commonly restrict "Allow log on locally" to specific
# privileged groups by default (unlike client Windows editions, where any local user gets it
# automatically) — a brand-new local standard user may not be able to log on interactively at
# all without this grant, which manifests as Start-Process -Credential silently doing nothing
# (no catchable exception) rather than a clear error.
#
# This is the well-known "LsaWrapper" pattern (originally circulated via a Microsoft support
# article, widely reproduced since) for calling LsaOpenPolicy/LsaAddAccountRights directly.
#
# See build-installer.yml's package-native-launcher-msix job and issue #116.

param(
    [Parameter(Mandatory = $true)]
    [string]$AccountName,

    [Parameter(Mandatory = $true)]
    [string]$PrivilegeName
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Security.Principal;

public class LsaRightsWrapper
{
    [StructLayout(LayoutKind.Sequential)]
    private struct LSA_UNICODE_STRING
    {
        public ushort Length;
        public ushort MaximumLength;
        public IntPtr Buffer;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct LSA_OBJECT_ATTRIBUTES
    {
        public int Length;
        public IntPtr RootDirectory;
        public LSA_UNICODE_STRING ObjectName;
        public int Attributes;
        public IntPtr SecurityDescriptor;
        public IntPtr SecurityQualityOfService;
    }

    private const int POLICY_CREATE_ACCOUNT = 0x00000010;

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern uint LsaOpenPolicy(
        ref LSA_UNICODE_STRING SystemName,
        ref LSA_OBJECT_ATTRIBUTES ObjectAttributes,
        int AccessMask,
        out IntPtr PolicyHandle);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern uint LsaAddAccountRights(
        IntPtr PolicyHandle,
        byte[] AccountSid,
        LSA_UNICODE_STRING[] UserRights,
        int CountOfRights);

    [DllImport("advapi32.dll")]
    private static extern int LsaClose(IntPtr ObjectHandle);

    [DllImport("advapi32.dll")]
    private static extern int LsaNtStatusToWinError(int status);

    private static LSA_UNICODE_STRING InitLsaString(string value)
    {
        var lsaString = new LSA_UNICODE_STRING();
        if (string.IsNullOrEmpty(value))
        {
            lsaString.Buffer = IntPtr.Zero;
            lsaString.Length = 0;
            lsaString.MaximumLength = 0;
            return lsaString;
        }
        lsaString.Buffer = Marshal.StringToHGlobalUni(value);
        lsaString.Length = (ushort)(value.Length * 2);
        lsaString.MaximumLength = (ushort)((value.Length + 1) * 2);
        return lsaString;
    }

    public static void AddPrivilege(string accountName, string privilegeName)
    {
        var account = new NTAccount(accountName);
        var sid = (SecurityIdentifier)account.Translate(typeof(SecurityIdentifier));
        byte[] sidBytes = new byte[sid.BinaryLength];
        sid.GetBinaryForm(sidBytes, 0);

        var systemName = new LSA_UNICODE_STRING();
        var objectAttributes = new LSA_OBJECT_ATTRIBUTES();
        objectAttributes.Length = Marshal.SizeOf(typeof(LSA_OBJECT_ATTRIBUTES));

        IntPtr policyHandle;
        uint status = LsaOpenPolicy(ref systemName, ref objectAttributes, POLICY_CREATE_ACCOUNT, out policyHandle);
        if (status != 0)
        {
            throw new Exception("LsaOpenPolicy failed, Win32 error " + LsaNtStatusToWinError((int)status));
        }

        try
        {
            var rights = new LSA_UNICODE_STRING[1];
            rights[0] = InitLsaString(privilegeName);

            status = LsaAddAccountRights(policyHandle, sidBytes, rights, 1);
            if (status != 0)
            {
                throw new Exception("LsaAddAccountRights failed, Win32 error " + LsaNtStatusToWinError((int)status));
            }
        }
        finally
        {
            LsaClose(policyHandle);
        }
    }
}
"@

[LsaRightsWrapper]::AddPrivilege($AccountName, $PrivilegeName)
Write-Host "Granted $PrivilegeName to $AccountName"
