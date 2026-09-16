# Install or update UnityBridge for Windows PowerShell.
[CmdletBinding()]
param(
    [string]$Repo = "zjxps2007/UnityBridge",
    [string]$Version = "latest",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "UnityBridge\bin"),
    [string]$AssetName = "",
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

function Get-FileSha256 {
    param([string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)) }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}

function Get-StandaloneAssetCandidates {
    if (-not [string]::IsNullOrWhiteSpace($AssetName)) {
        return @($AssetName)
    }

    # New releases unpack once at installation. Keep legacy releases installable.
    return @(
        "unity-bridge-windows-amd64.zip",
        "unity-bridge-windows-amd64.exe",
        "unity-bridge-windows-x64.exe"
    )
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
        throw "Failed to resolve GitHub release '$ReleaseVersion' in $repoName. Make sure the release exists and contains a Windows standalone asset, or run with -PythonMode."
    }
}

function Install-Standalone {
    Write-Step "Resolving UnityBridge release"
    $release = Resolve-GitHubRelease -Repository $Repo -ReleaseVersion $Version
    $assets = @($release.assets)
    $assetCandidates = Get-StandaloneAssetCandidates
    $asset = $null
    foreach ($candidate in $assetCandidates) {
        $asset = $assets | Where-Object { $_.name -eq $candidate } | Select-Object -First 1
        if ($null -ne $asset) {
            break
        }
    }
    if ($null -eq $asset) {
        $available = ($assets | ForEach-Object { $_.name }) -join ", "
        if ([string]::IsNullOrWhiteSpace($available)) {
            $available = "(none)"
        }
        $expected = $assetCandidates -join ", "
        throw "Release '$($release.tag_name)' does not contain a supported Windows asset. Expected one of: $expected. Available assets: $available. Run with -PythonMode to install from source."
    }

    Write-Step "Downloading $($asset.name) from $($release.tag_name)"
    $installRoot = [System.IO.Path]::GetFullPath($InstallDir)
    New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
    $stage = Join-Path $installRoot (".unity-bridge-stage-" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $stage | Out-Null
    $tempPath = Join-Path $stage "download.zip"
    $targetPath = Join-Path $installRoot "unity-bridge.exe"
    try {
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tempPath -Headers (Get-GitHubHeaders)
        $runtime = $null
        if ($asset.name.EndsWith(".zip", [StringComparison]::OrdinalIgnoreCase)) {
            $unpack = Join-Path $stage "unpacked"
            Expand-Archive -LiteralPath $tempPath -DestinationPath $unpack
            $bundle = Join-Path $unpack "unity-bridge"
            $candidate = Join-Path $bundle "unity-bridge.exe"
            $runtimes = @(Get-ChildItem -LiteralPath $bundle -Directory -Filter '_unity_bridge_runtime_*')
            if ($runtimes.Count -ne 1 -or $runtimes[0].Name -notmatch '^_unity_bridge_runtime_[0-9a-f]{32}$' -or
                -not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                throw "Invalid standalone bundle layout."
            }
            $runtime = $runtimes[0]
            Get-ChildItem -LiteralPath $bundle -Recurse -File | Unblock-File
        }
        else {
            $candidate = Join-Path $stage "unity-bridge.exe"
            Move-Item -LiteralPath $tempPath -Destination $candidate
            Unblock-File -LiteralPath $candidate
        }

        Write-Step "Verifying downloaded unity-bridge"
        & $candidate --help *> $null
        if ($LASTEXITCODE -ne 0) { throw "Downloaded unity-bridge.exe verification failed; existing installation was preserved." }

        $hasHost = $null -ne $runtime -and (Test-Path -LiteralPath (Join-Path $runtime.FullName 'host-manifest.json'))
        if ($hasHost) {
            $stagedWorker = Join-Path $runtime.FullName 'compiler\UnityBridge.Compiler.exe'
            if (-not (Test-Path -LiteralPath $stagedWorker -PathType Leaf)) { throw 'Compiler worker is missing from the bundle.' }
            & $candidate _host check-worker --worker $stagedWorker *> $null
            if ($LASTEXITCODE -ne 0) { throw 'Compiler worker verification failed; existing installation was preserved.' }
        }

        if ($null -ne $runtime) {
            $runtimeTarget = Join-Path $installRoot $runtime.Name
            if (Test-Path -LiteralPath $runtimeTarget) {
                # Reinstalling the same build reuses its immutable runtime only if
                # every file still matches. Never overlay a partially mixed runtime.
                $sourceFiles = @(Get-ChildItem -LiteralPath $runtime.FullName -Recurse -File)
                if (@(Get-ChildItem -LiteralPath $runtimeTarget -Recurse -File).Count -ne $sourceFiles.Count) {
                    throw "Installed runtime is modified: $runtimeTarget. Close UnityBridge processes and remove this runtime folder before reinstalling."
                }
                foreach ($file in $sourceFiles) {
                    $relative = $file.FullName.Substring($runtime.FullName.Length + 1)
                    $existing = Join-Path $runtimeTarget $relative
                    if (-not (Test-Path -LiteralPath $existing -PathType Leaf) -or
                        (Get-FileSha256 $file.FullName) -ne (Get-FileSha256 $existing)) {
                        throw "Installed runtime is incomplete or modified: $runtimeTarget. Close UnityBridge processes and remove this runtime folder before reinstalling."
                    }
                }
            }
            else {
                foreach ($directory in @($runtime.FullName, $runtimeTarget)) {
                    if (-not ([System.IO.Path]::GetFullPath($directory)).StartsWith($installRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
                        throw "Refusing to move a runtime outside the installation directory."
                    }
                }
                Move-Item -LiteralPath $runtime.FullName -Destination $runtimeTarget
            }
        }
        if (Test-Path -LiteralPath $targetPath) {
            [System.IO.File]::Replace($candidate, $targetPath, (Join-Path $stage 'previous.exe'))
        }
        else {
            [System.IO.File]::Move($candidate, $targetPath)
        }
        if ($hasHost) {
            $installedWorker = Join-Path $runtimeTarget 'compiler\UnityBridge.Compiler.exe'
            & $targetPath _host register --executable $targetPath --worker $installedWorker *> $null
            if ($LASTEXITCODE -ne 0) {
                $previous = Join-Path $stage 'previous.exe'
                if (Test-Path -LiteralPath $previous) {
                    [System.IO.File]::Replace($previous, $targetPath, (Join-Path $stage 'failed.exe'))
                }
                throw 'Host registration failed. Check access to the user UnityBridge configuration directory.'
            }
        }
    }
    finally {
        $stageFullPath = [System.IO.Path]::GetFullPath($stage)
        if (-not $stageFullPath.StartsWith($installRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean a staging path outside the installation directory."
        }
        Remove-Item -LiteralPath $stageFullPath -Recurse -Force -ErrorAction SilentlyContinue
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
