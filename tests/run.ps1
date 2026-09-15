param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$testsRoot = Split-Path -Parent $PSCommandPath
$workspace = Split-Path -Parent $testsRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host "`n=== $Label ==="
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

Push-Location $workspace
try {
    Write-Host "`n=== PowerShell syntax ==="
    foreach ($script in Get-ChildItem -LiteralPath $workspace -Filter '*.ps1' -File -Recurse) {
        if ($script.FullName -match '[\\/](?:build[^\\/]*|\.git|\.claude)[\\/]') {
            continue
        }
        $tokens = $null
        $errors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile(
            $script.FullName, [ref]$tokens, [ref]$errors)
        if (@($errors).Count -gt 0) {
            throw "$($script.FullName): $((@($errors) | ForEach-Object Message) -join '; ')"
        }
    }

    Invoke-Checked 'Python syntax' {
        python -m compileall -q xt30-battery root-adb
    }
    Invoke-Checked 'Generated XT30 Battery Mod Lab script' {
        python xt30-battery/build_lab_script.py --check
    }

    Invoke-Checked 'Hacks repository tests' {
        python -m unittest discover -s tests -p 'test_*.py'
    }
    Invoke-Checked 'Windows patch self-test' {
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
            windows-offline\scripts\patch_robomaster_windows.ps1 -Action SelfTest
    }
}
finally {
    Pop-Location
}

Write-Host "`nAll Hacks checks passed."
