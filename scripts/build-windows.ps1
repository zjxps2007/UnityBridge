# Build the standalone Windows UnityBridge CLI executable.
[CmdletBinding()]
param(
    [string]$OutputName = "unity-bridge-windows-x64.exe",
    [switch]$SkipDependencyInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if (-not $SkipDependencyInstall) {
        python -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
        python -m pip install -e ".[build]"
        if ($LASTEXITCODE -ne 0) { throw "build dependency install failed." }
    }

    python -m PyInstaller `
        --clean `
        --noconfirm `
        --onefile `
        --name unity-bridge `
        --paths src `
        scripts\pyinstaller_entry.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $source = Join-Path $root "dist\unity-bridge.exe"
    $target = Join-Path $root "dist\$OutputName"
    Copy-Item -LiteralPath $source -Destination $target -Force
    Write-Host "Built $target" -ForegroundColor Green
}
finally {
    Pop-Location
}
