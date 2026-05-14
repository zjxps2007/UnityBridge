# Install or update UnityBridge for Windows PowerShell.
[CmdletBinding()]
param(
    [string]$Repo = "zjxps2007/UnityBridge",
    [string]$Version = "latest",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "UnityBridge\bin"),
    [string]$AssetName = "unity-bridge-windows-x64.exe",
    [string]$PackageSpec = "git+https://github.com/zjxps2007/UnityBridge.git",
    [switch]$PythonMode,
    [switch]$NoPathUpdate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if ($PSBoundParameters.ContainsKey("PackageSpec") -and -not $PythonMode) {
    $PythonMode = $true
}

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Normalize-PathEntry {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }
    try {
        return [System.IO.Path]::GetFullPath($Value).TrimEnd("\")
    }
    catch {
        return $Value.TrimEnd("\")
    }
}

function Test-PathContains {
    param(
        [string]$PathValue,
        [string]$Entry
    )

    if ([string]::IsNullOrWhiteSpace($PathValue) -or [string]::IsNullOrWhiteSpace($Entry)) {
        return $false
    }

    $target = Normalize-PathEntry $Entry
    foreach ($part in ($PathValue -split ";")) {
        if ([string]::IsNullOrWhiteSpace($part)) {
            continue
        }
        if ((Normalize-PathEntry $part) -ieq $target) {
            return $true
        }
    }
    return $false
}

function Add-PathEntryForCurrentSession {
    param([string]$Entry)
    if ([string]::IsNullOrWhiteSpace($Entry) -or (Test-PathContains $env:Path $Entry)) {
        return
    }
    if ([string]::IsNullOrWhiteSpace($env:Path)) {
        $env:Path = $Entry
    }
    else {
        $env:Path = "$env:Path;$Entry"
    }
}

function Add-UserPathEntry {
    param([string]$Entry)
    if ([string]::IsNullOrWhiteSpace($Entry)) {
        return
    }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($null -eq $userPath) {
        $userPath = ""
    }
    if (Test-PathContains $userPath $Entry) {
        return
    }

    $newPath = if ([string]::IsNullOrWhiteSpace($userPath)) {
        $Entry
    }
    else {
        "$userPath;$Entry"
    }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Step "Added to user PATH: $Entry"
}

function Get-GitHubHeaders {
    return @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "UnityBridge installer"
    }
}

function Resolve-GitHubRelease {
    param(
        [string]$Repository,
        [string]$ReleaseVersion
    )

    $repoName = $Repository.Trim().Trim("/")
    if ([string]::IsNullOrWhiteSpace($repoName) -or -not $repoName.Contains("/")) {
        throw "Repo must be in owner/name form. Received: $Repository"
    }

    if ([string]::IsNullOrWhiteSpace($ReleaseVersion) -or $ReleaseVersion -ieq "latest") {
        $url = "https://api.github.com/repos/$repoName/releases/latest"
    }
    else {
        $tag = [System.Uri]::EscapeDataString($ReleaseVersion)
        $url = "https://api.github.com/repos/$repoName/releases/tags/$tag"
    }

    try {
        return Invoke-RestMethod -Uri $url -Headers (Get-GitHubHeaders)
    }
    catch {
        throw "Failed to resolve GitHub release '$ReleaseVersion' in $repoName. Make sure the release exists and contains $AssetName, or run with -PythonMode."
    }
}

function Install-Standalone {
    Write-Step "Resolving UnityBridge release"
    $release = Resolve-GitHubRelease -Repository $Repo -ReleaseVersion $Version
    $assets = @($release.assets)
    $asset = $assets | Where-Object { $_.name -eq $AssetName } | Select-Object -First 1
    if ($null -eq $asset) {
        $available = ($assets | ForEach-Object { $_.name }) -join ", "
        if ([string]::IsNullOrWhiteSpace($available)) {
            $available = "(none)"
        }
        throw "Release '$($release.tag_name)' does not contain $AssetName. Available assets: $available. Run with -PythonMode to install from source."
    }

    Write-Step "Downloading $AssetName from $($release.tag_name)"
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

    $tempPath = Join-Path ([System.IO.Path]::GetTempPath()) ("unity-bridge-" + [System.Guid]::NewGuid().ToString("N") + ".exe")
    $targetPath = Join-Path $InstallDir "unity-bridge.exe"
    try {
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tempPath -Headers (Get-GitHubHeaders)
        Move-Item -LiteralPath $tempPath -Destination $targetPath -Force
        try { Unblock-File -LiteralPath $targetPath } catch { }
    }
    finally {
        if (Test-Path $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
        }
    }

    $aliasPath = Join-Path $InstallDir "unity_bridge.cmd"
    $aliasContent = @'
@echo off
"%~dp0unity-bridge.exe" %*
'@
    Set-Content -LiteralPath $aliasPath -Value $aliasContent -Encoding ASCII

    if (-not $NoPathUpdate) {
        Add-UserPathEntry $InstallDir
    }
    Add-PathEntryForCurrentSession $InstallDir

    Write-Step "Verifying unity-bridge"
    & $targetPath --help *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "unity-bridge.exe verification failed."
    }

    Write-Host ""
    Write-Host "UnityBridge standalone CLI is installed." -ForegroundColor Green
    Write-Host "Install dir: $InstallDir"
    Write-Host "Try: unity-bridge status"
}

function Test-PythonCandidate {
    param(
        [string]$CommandName,
        [string[]]$PrefixArgs
    )

    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        return $false
    }

    $probeArgs = @($PrefixArgs) + @(
        "-c",
        "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    )
    & $command.Source @probeArgs *> $null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    $script:PythonCommand = $command.Source
    $script:PythonArgs = @($PrefixArgs)
    return $true
}

function Find-Python {
    if (Test-PythonCandidate "py" @("-3")) {
        return
    }
    if (Test-PythonCandidate "python" @()) {
        return
    }
    if (Test-PythonCandidate "python3" @()) {
        return
    }

    throw "Python 3.10 or newer was not found. Install Python, then run this installer again or use standalone mode after a release asset is published."
}

function Invoke-Python {
    param([string[]]$Arguments)
    $allArgs = @($script:PythonArgs) + @($Arguments)
    & $script:PythonCommand @allArgs
}

function Get-PythonScriptDirs {
    $script = @'
import json
import os
import site
import sysconfig

paths = []

def add(path):
    if path and path not in paths:
        paths.append(path)

add(sysconfig.get_path('scripts'))

scheme = 'nt_user' if os.name == 'nt' else 'posix_user'
try:
    add(sysconfig.get_path('scripts', scheme))
except Exception:
    pass

try:
    user_base = site.getuserbase()
    if os.name == 'nt':
        version = 'Python' + sysconfig.get_python_version().replace('.', '')
        add(os.path.join(user_base, version, 'Scripts'))
    else:
        add(os.path.join(user_base, 'bin'))
except Exception:
    pass

print(json.dumps(paths))
'@

    $json = Invoke-Python @("-c", $script)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to locate Python script directories."
    }
    return @($json | ConvertFrom-Json)
}

function Find-UnityBridgeScriptDir {
    $dirs = Get-PythonScriptDirs
    foreach ($dir in $dirs) {
        if ([string]::IsNullOrWhiteSpace($dir)) {
            continue
        }
        if ((Test-Path (Join-Path $dir "unity-bridge.exe")) -or (Test-Path (Join-Path $dir "unity-bridge"))) {
            return $dir
        }
    }
    foreach ($dir in $dirs) {
        if (-not [string]::IsNullOrWhiteSpace($dir)) {
            return $dir
        }
    }
    return $null
}

function Install-PythonPackage {
    Write-Step "Finding Python 3.10+"
    Find-Python

    Write-Step "Installing UnityBridge Python package"
    Invoke-Python @("-m", "pip", "install", "--upgrade", $PackageSpec)
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed."
    }

    $scriptDir = Find-UnityBridgeScriptDir
    if (-not [string]::IsNullOrWhiteSpace($scriptDir)) {
        if (-not $NoPathUpdate) {
            Add-UserPathEntry $scriptDir
        }
        Add-PathEntryForCurrentSession $scriptDir
    }

    $bridgeCommand = Get-Command "unity-bridge" -ErrorAction SilentlyContinue
    if ($null -eq $bridgeCommand -and -not [string]::IsNullOrWhiteSpace($scriptDir)) {
        $bridgePath = Join-Path $scriptDir "unity-bridge.exe"
        if (Test-Path $bridgePath) {
            $bridgeCommand = Get-Command $bridgePath -ErrorAction SilentlyContinue
        }
    }

    if ($null -ne $bridgeCommand) {
        Write-Step "Verifying unity-bridge"
        & $bridgeCommand.Source --help *> $null
    }

    Write-Host ""
    Write-Host "UnityBridge Python package is installed." -ForegroundColor Green
    Write-Host "Try: unity-bridge status"
    Write-Host "Fallback: python -m unity_bridge status"
}

if ($PythonMode) {
    Install-PythonPackage
}
else {
    Install-Standalone
}
