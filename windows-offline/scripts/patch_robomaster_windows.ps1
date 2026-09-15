[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('Status', 'Apply', 'Restore', 'SelfTest')]
    [string]$Action = 'Status',

    [string]$InstallRoot = 'C:\Program Files\DJI Product\RoboMaster'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$originalSha256 = '8914F8031749CD4D08EDC556BE293783C421C918DE8B4A5FB3C9F9F6B5304371'
$offlinePatchedSha256 = '1533520D733EAF4FBD031465784867E862760FAEF7B9E7367DD7961B076BC80E'
$managedPath = Join-Path $InstallRoot 'RoboMaster_Data\Managed'
$assemblyPath = Join-Path $managedPath 'Assembly-CSharp.dll'
$backupPath = "$assemblyPath.robomaster-preservation-original.bak"
$legacyBackupPath = "$assemblyPath.codex-original.bak"

[byte[]]$redirectOriginal = @(0x17)
[byte[]]$redirectPatched = @(0x1A)
[byte[]]$menuTokenCheckOriginal = @(0x6F, 0x6A, 0x2B, 0x00, 0x06)
[byte[]]$menuTokenCheckPatched = @(0x26, 0x26, 0x00, 0x00, 0x00)
[byte[]]$commonDataPathOriginal = @(0x89, 0x08, 0x00, 0x0A)
[byte[]]$commonDataPathPatched = @(0x1D, 0x05, 0x00, 0x0A)
[byte[]]$managerDataPathOriginal = @(0x40, 0x1C, 0x00, 0x06)
[byte[]]$managerDataPathPatched = @(0x3E, 0x1C, 0x00, 0x06)
[byte[]]$privacyGateOriginal = @(0x72, 0x0C, 0x21, 0x00, 0x70, 0x28, 0xB3, 0x02, 0x00, 0x0A, 0x2A)
[byte[]]$privacyGatePatched = @(0x17, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x2A)
[byte[]]$storedLoginOriginal = @(0x17)
[byte[]]$storedLoginPatched = @(0x16)

# Target=True is the exact locally verified offline patch. The two guest-state
# signatures are detection guards only and deliberately remain original.
$patchDefinitions = @(
    [pscustomobject]@{ Name = 'Startup'; Offset = 0x0000F09E; Original = $redirectOriginal; Patched = $redirectPatched; Target = $true }
    [pscustomobject]@{ Name = 'MenuTokenCheck'; Offset = 0x0000F44A; Original = $menuTokenCheckOriginal; Patched = $menuTokenCheckPatched; Target = $true }
    [pscustomobject]@{ Name = 'TokenInvalid'; Offset = 0x0000EE37; Original = $redirectOriginal; Patched = $redirectPatched; Target = $true }
    [pscustomobject]@{ Name = 'Logout'; Offset = 0x0000F525; Original = $redirectOriginal; Patched = $redirectPatched; Target = $true }
    [pscustomobject]@{ Name = 'OfflinePrivacyGate'; Offset = 0x0000EE62; Original = $privacyGateOriginal; Patched = $privacyGatePatched; Target = $false }
    [pscustomobject]@{ Name = 'StoredLoginState'; Offset = 0x000DCAC0; Original = $storedLoginOriginal; Patched = $storedLoginPatched; Target = $false }
    [pscustomobject]@{ Name = 'CommonDataPath'; Offset = 0x0009C30F; Original = $commonDataPathOriginal; Patched = $commonDataPathPatched; Target = $true }
    [pscustomobject]@{ Name = 'SettingDataPath'; Offset = 0x000A02C8; Original = $managerDataPathOriginal; Patched = $managerDataPathPatched; Target = $true }
    [pscustomobject]@{ Name = 'StatisticDataPath'; Offset = 0x000A0BC4; Original = $managerDataPathOriginal; Patched = $managerDataPathPatched; Target = $true }
)

function Test-BytesAtOffset {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Data,
        [Parameter(Mandatory = $true)][int]$Offset,
        [Parameter(Mandatory = $true)][byte[]]$Expected
    )

    if ($Offset -lt 0 -or ($Offset + $Expected.Length) -gt $Data.Length) {
        return $false
    }
    for ($index = 0; $index -lt $Expected.Length; $index++) {
        if ($Data[$Offset + $index] -ne $Expected[$index]) {
            return $false
        }
    }
    return $true
}

function Set-BytesAtOffset {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Data,
        [Parameter(Mandatory = $true)][int]$Offset,
        [Parameter(Mandatory = $true)][byte[]]$Value
    )

    [System.Array]::Copy($Value, 0, $Data, $Offset, $Value.Length)
}

function Get-PatchLayout {
    param([Parameter(Mandatory = $true)][byte[]]$Data)

    $states = [ordered]@{}
    foreach ($definition in $patchDefinitions) {
        $isOriginal = Test-BytesAtOffset $Data $definition.Offset $definition.Original
        $isPatched = Test-BytesAtOffset $Data $definition.Offset $definition.Patched
        if ($isOriginal -eq $isPatched) {
            $states[$definition.Name] = 'Unknown'
        }
        elseif ($isPatched) {
            $states[$definition.Name] = 'Patched'
        }
        else {
            $states[$definition.Name] = 'Original'
        }
    }

    $unknown = @($states.Values | Where-Object { $_ -eq 'Unknown' }).Count
    $patchedTargets = @($patchDefinitions | Where-Object {
        $_.Target -and $states[$_.Name] -eq 'Patched'
    }).Count
    $originalTargets = @($patchDefinitions | Where-Object {
        $_.Target -and $states[$_.Name] -eq 'Original'
    }).Count
    $patchedGuards = @($patchDefinitions | Where-Object {
        -not $_.Target -and $states[$_.Name] -eq 'Patched'
    }).Count
    $targetCount = @($patchDefinitions | Where-Object Target).Count
    $guardCount = $patchDefinitions.Count - $targetCount

    $state = 'MixedOrUnknown'
    if ($unknown -eq 0 -and $originalTargets -eq $targetCount -and $patchedGuards -eq 0) {
        $state = 'Original'
    }
    elseif ($unknown -eq 0 -and $patchedTargets -eq $targetCount -and $patchedGuards -eq 0) {
        $state = 'OfflinePatched'
    }
    elseif ($unknown -eq 0 -and $patchedTargets -eq 4 -and $originalTargets -eq 3 -and $patchedGuards -eq 0) {
        $state = 'PreviousPatch'
    }
    elseif ($unknown -eq 0 -and $patchedTargets -eq $targetCount -and $patchedGuards -eq $guardCount) {
        $state = 'UnsupportedFullPatch'
    }

    return [pscustomobject]@{ State = $state; Definitions = $states }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToUpperInvariant()
}

function Assert-RoboMasterStopped {
    $normalizedRoot = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\') + '\'
    $running = @(Get-Process -Name 'RoboMaster' -ErrorAction SilentlyContinue | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_.Path) -and
        [System.IO.Path]::GetFullPath($_.Path).StartsWith(
            $normalizedRoot,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    })
    if ($running.Count -gt 0) {
        throw 'RoboMaster is running from the target installation. Close it first.'
    }
}

function Get-ValidatedBackup {
    foreach ($candidate in @($backupPath, $legacyBackupPath)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        if ((Get-Sha256 $candidate) -ne $originalSha256) {
            continue
        }
        $bytes = [System.IO.File]::ReadAllBytes($candidate)
        if ((Get-PatchLayout $bytes).State -eq 'Original') {
            return $candidate
        }
    }
    throw 'No validated original backup is available.'
}

function Ensure-CanonicalBackup {
    param(
        [Parameter(Mandatory = $true)][string]$CurrentState,
        [Parameter(Mandatory = $true)][string]$CurrentHash
    )

    if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
        if ((Get-Sha256 $backupPath) -ne $originalSha256 -or
            (Get-PatchLayout ([System.IO.File]::ReadAllBytes($backupPath))).State -ne 'Original') {
            throw "Canonical backup is invalid: $backupPath"
        }
        return $backupPath
    }

    $source = $null
    if ($CurrentState -eq 'Original' -and $CurrentHash -eq $originalSha256) {
        $source = $assemblyPath
    }
    elseif (Test-Path -LiteralPath $legacyBackupPath -PathType Leaf) {
        $source = Get-ValidatedBackup
    }
    else {
        throw 'Cannot apply or confirm the patch without a validated original backup.'
    }

    [System.IO.File]::Copy($source, $backupPath, $false)
    if ((Get-Sha256 $backupPath) -ne $originalSha256) {
        throw 'The newly created backup failed its hash check.'
    }
    return $backupPath
}

function Write-AssemblyAtomically {
    param([Parameter(Mandatory = $true)][byte[]]$Data)

    $temporaryPath = "$assemblyPath.robomaster-preservation-$PID.tmp"
    $replaceBackupPath = "$assemblyPath.robomaster-preservation-replace-$PID.bak"
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
    if (Test-Path -LiteralPath $replaceBackupPath) {
        Remove-Item -LiteralPath $replaceBackupPath -Force
    }
    try {
        [System.IO.File]::WriteAllBytes($temporaryPath, $Data)
        [void][System.Reflection.AssemblyName]::GetAssemblyName($temporaryPath)
        [System.IO.File]::Replace(
            $temporaryPath,
            $assemblyPath,
            $replaceBackupPath,
            $true
        )
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
        if (Test-Path -LiteralPath $replaceBackupPath) {
            Remove-Item -LiteralPath $replaceBackupPath -Force
        }
    }
}

function Invoke-SelfTest {
    $length = ($patchDefinitions | ForEach-Object {
        $_.Offset + [Math]::Max($_.Original.Length, $_.Patched.Length)
    } | Measure-Object -Maximum).Maximum
    [byte[]]$sample = New-Object byte[] $length
    foreach ($definition in $patchDefinitions) {
        Set-BytesAtOffset $sample $definition.Offset $definition.Original
    }
    if ((Get-PatchLayout $sample).State -ne 'Original') {
        throw 'Self-test could not identify the synthetic original layout.'
    }
    foreach ($definition in $patchDefinitions | Where-Object Target) {
        Set-BytesAtOffset $sample $definition.Offset $definition.Patched
    }
    if ((Get-PatchLayout $sample).State -ne 'OfflinePatched') {
        throw 'Self-test could not identify the synthetic patched layout.'
    }
    foreach ($definition in $patchDefinitions | Where-Object Target) {
        Set-BytesAtOffset $sample $definition.Offset $definition.Original
    }
    if ((Get-PatchLayout $sample).State -ne 'Original') {
        throw 'Self-test restore failed.'
    }
    Write-Host 'SELFTEST PASS: original -> offline patched -> original'
}

if ($Action -eq 'SelfTest') {
    Invoke-SelfTest
    return
}

if (-not (Test-Path -LiteralPath $assemblyPath -PathType Leaf)) {
    throw "Assembly not found: $assemblyPath"
}

$currentBytes = [System.IO.File]::ReadAllBytes($assemblyPath)
$currentLayout = Get-PatchLayout $currentBytes
$currentHash = Get-Sha256 $assemblyPath
$supported = (
    ($currentLayout.State -eq 'Original' -and $currentHash -eq $originalSha256) -or
    ($currentLayout.State -eq 'OfflinePatched' -and $currentHash -eq $offlinePatchedSha256)
)

switch ($Action) {
    'Status' {
        [pscustomobject]@{
            Assembly = $assemblyPath
            State = $currentLayout.State
            Supported = $supported
            Sha256 = $currentHash
            Backup = if (Test-Path -LiteralPath $backupPath) {
                $backupPath
            }
            elseif (Test-Path -LiteralPath $legacyBackupPath) {
                "$legacyBackupPath (legacy name)"
            }
            else {
                'Missing'
            }
        } | Format-List
    }

    'Apply' {
        Assert-RoboMasterStopped
        if ($currentLayout.State -notin @('Original', 'PreviousPatch', 'OfflinePatched')) {
            throw "Unsupported assembly layout: $($currentLayout.State)"
        }
        if ($currentLayout.State -eq 'Original' -and $currentHash -ne $originalSha256) {
            throw "Original-looking assembly has an unsupported hash: $currentHash"
        }
        if ($currentLayout.State -eq 'OfflinePatched' -and $currentHash -ne $offlinePatchedSha256) {
            throw "Patched-looking assembly has an unsupported hash: $currentHash"
        }

        if (-not $PSCmdlet.ShouldProcess($assemblyPath, 'Apply verified RoboMaster offline patch')) {
            return
        }
        [void](Ensure-CanonicalBackup $currentLayout.State $currentHash)
        if ($currentLayout.State -eq 'OfflinePatched') {
            Write-Host 'Offline patch is already active; validated backup is available.'
            return
        }

        [byte[]]$patchedBytes = $currentBytes.Clone()
        foreach ($definition in $patchDefinitions | Where-Object Target) {
            Set-BytesAtOffset $patchedBytes $definition.Offset $definition.Patched
        }
        $candidatePath = "$assemblyPath.robomaster-preservation-candidate-$PID.tmp"
        try {
            [System.IO.File]::WriteAllBytes($candidatePath, $patchedBytes)
            $candidateHash = Get-Sha256 $candidatePath
        }
        finally {
            if (Test-Path -LiteralPath $candidatePath) {
                Remove-Item -LiteralPath $candidatePath -Force
            }
        }
        if ($candidateHash -ne $offlinePatchedSha256 -or
            (Get-PatchLayout $patchedBytes).State -ne 'OfflinePatched') {
            throw "Generated patch failed verification: $candidateHash"
        }

        try {
            Write-AssemblyAtomically $patchedBytes
            if ((Get-Sha256 $assemblyPath) -ne $offlinePatchedSha256) {
                throw 'Installed patch failed its final hash check.'
            }
        }
        catch {
            $originalBytes = [System.IO.File]::ReadAllBytes((Get-ValidatedBackup))
            Write-AssemblyAtomically $originalBytes
            throw
        }
        Write-Host "Offline patch applied: $assemblyPath"
    }

    'Restore' {
        Assert-RoboMasterStopped
        if ($currentLayout.State -eq 'Original' -and $currentHash -eq $originalSha256) {
            Write-Host 'The supported original assembly is already active.'
            return
        }
        $validatedBackup = Get-ValidatedBackup
        if (-not $PSCmdlet.ShouldProcess($assemblyPath, "Restore from $validatedBackup")) {
            return
        }
        $originalBytes = [System.IO.File]::ReadAllBytes($validatedBackup)
        Write-AssemblyAtomically $originalBytes
        if ((Get-Sha256 $assemblyPath) -ne $originalSha256 -or
            (Get-PatchLayout ([System.IO.File]::ReadAllBytes($assemblyPath))).State -ne 'Original') {
            throw 'Restore failed final verification.'
        }
        Write-Host "Original assembly restored: $assemblyPath"
    }
}
