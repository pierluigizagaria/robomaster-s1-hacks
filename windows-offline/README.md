# Windows Offline Patch

This tool keeps one known installation of the RoboMaster Windows application
usable when the remote account/login flow no longer completes. It patches only
the owner's local `Assembly-CSharp.dll`; no DJI binary is distributed.

## Compatibility

The script supports exactly these SHA-256 states:

| State | SHA-256 |
|---|---|
| Original | `8914F8031749CD4D08EDC556BE293783C421C918DE8B4A5FB3C9F9F6B5304371` |
| Offline patched | `1533520D733EAF4FBD031465784867E862760FAEF7B9E7367DD7961B076BC80E` |

The observed `RoboMaster.exe` reports file version `2019.2.3.9328066`. The hash,
file length, and every byte signature are checked; the displayed version alone
is not sufficient. Unknown or mixed layouts fail closed.

## Use

Close RoboMaster and open PowerShell as Administrator. Check the installation:

```powershell
.\windows-offline\scripts\patch_robomaster_windows.ps1 -Action Status
```

Apply the offline patch:

```powershell
.\windows-offline\scripts\patch_robomaster_windows.ps1 -Action Apply
```

The first apply creates
`Assembly-CSharp.dll.robomaster-preservation-original.bak`, validates its hash,
generates the known patched bytes in memory, validates the expected patched
hash, and replaces the assembly on the same volume. An existing
`.codex-original.bak` is also accepted after validation and is never modified.

For a non-mutating preview, append `-WhatIf`.

## Restore

Close RoboMaster, then run:

```powershell
.\windows-offline\scripts\patch_robomaster_windows.ps1 -Action Restore
```

Restore accepts only a backup with the exact original hash and byte layout. Run
`-Action Status` afterward and confirm `State : Original` and `Supported : True`.
Restore before allowing the vendor installer to update or repair the app.

## Self-test

The byte-layout engine can be tested without an installed app or binary:

```powershell
.\windows-offline\scripts\patch_robomaster_windows.ps1 -Action SelfTest
```

## Boundaries

- This is an availability workaround for an obsolete client, not an account
  credential, server emulator, or network-service replacement.
- It is not compatible with another assembly unless that version is analyzed,
  documented, and added with its own hashes and fixtures.
- Application logs and data can contain account information. Do not attach raw
  files to public issues.
