# Build the standalone Windows UnityBridge CLI executable.
[CmdletBinding()]
param(
    [string]$OutputName = "unity-bridge-windows-amd64.exe",
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

    python scripts\build-standalone.py --output-name $OutputName
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
}
finally {
    Pop-Location
}
