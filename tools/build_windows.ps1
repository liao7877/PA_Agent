# Build Trading Agent Windows distributable (PyInstaller onedir).
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File tools/build_windows.ps1
#
# Options:
#   -Installer     Also build dist/Trading_Agent_Setup.exe (requires Inno Setup 6)
#   -Clean         Remove build/ and dist/Trading_Agent before building
#   -SkipTests     Skip unit tests before packaging
#   -SkipInstall   Skip pip install -e . (use when venv/deps are already ready)
#
# See docs/构建EXE.md for full instructions.

param(
    [switch]$Installer,
    [switch]$Clean,
    [switch]$SkipTests,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-ProjectVersion {
    $pyproject = Join-Path $Root "pyproject.toml"
    if (-not (Test-Path $pyproject)) {
        return "unknown"
    }
    foreach ($line in Get-Content $pyproject) {
        if ($line -match '^\s*version\s*=\s*"(.+)"\s*$') {
            return $Matches[1]
        }
    }
    return "unknown"
}

function Assert-PythonReady {
    $versionText = & python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python not found. Install Python 3.11+ and ensure 'python' is on PATH."
    }
    if ($versionText -notmatch 'Python (\d+)\.(\d+)') {
        throw "Unexpected python --version output: $versionText"
    }
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
        throw "Python 3.11+ required, got $versionText"
    }
    Write-Host "Python: $versionText"
}

function Remove-BuildArtifacts {
    $targets = @(
        (Join-Path $Root "build"),
        (Join-Path $Root "dist\Trading_Agent")
    )
    foreach ($path in $targets) {
        if (Test-Path $path) {
            Write-Host "Removing $path"
            Remove-Item -Recurse -Force $path
        }
    }
}

$Version = Get-ProjectVersion
Write-Step "Trading Agent Windows build (version $Version)"
Assert-PythonReady

if ($Clean) {
    Write-Step "Cleaning previous build artifacts"
    Remove-BuildArtifacts
}

if (-not $SkipInstall) {
    Write-Step "Installing project dependencies"
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"
    python -m pip install pyinstaller
} else {
    Write-Step "Skipping pip install (-SkipInstall)"
    python -m pip install pyinstaller
}

$publicKey = Join-Path $Root "pa_agent\licensing\public_key.pem"
if (-not (Test-Path $publicKey)) {
    throw "Missing licensing public key: $publicKey`nRun: python tools/license_keygen.py generate-keys"
}

Write-Step "Syncing embedded public key"
python tools/sync_embedded_pubkey.py
if ($LASTEXITCODE -ne 0) { throw "sync_embedded_pubkey failed" }

if (Test-Path (Join-Path $Root "config\settings.json")) {
    Write-Host "Note: config\settings.json exists locally but will NOT be packaged (only settings.example.json)."
}

if (-not $SkipTests) {
    Write-Step "Running unit tests (tests/unit)"
    python -m pytest tests/unit -q
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed. Fix tests or pass -SkipTests to bypass."
    }
}

Write-Step "Building with PyInstaller"
python -m PyInstaller --noconfirm Trading_Agent.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$DistDir = Join-Path $Root "dist\Trading_Agent"
$ExePath = Join-Path $DistDir "Trading_Agent.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build failed: Trading_Agent.exe not found in $DistDir"
}

Write-Step "Verifying build does not contain private config"
powershell -ExecutionPolicy Bypass -File (Join-Path $Root "tools\verify_build_safe.ps1") -DistDir $DistDir

$exeInfo = Get-Item $ExePath
Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host "  Version : $Version"
Write-Host "  Exe     : $ExePath"
Write-Host "  Size    : $([math]::Round($exeInfo.Length / 1MB, 2)) MB"
Write-Host "  Folder  : $DistDir"
Write-Host ""
Write-Host "Distribute the entire dist\Trading_Agent\ folder, or use -Installer to create a setup exe."

if ($Installer) {
    $Iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $Iscc) {
        throw "Inno Setup 6 not found. Install from https://jrsoftware.org/isinfo.php"
    }

    Write-Step "Building installer with Inno Setup"
    & $Iscc (Join-Path $Root "tools\installer.iss")
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE"
    }

    $setupPath = Join-Path $Root "dist\Trading_Agent_Setup.exe"
    if (-not (Test-Path $setupPath)) {
        throw "Installer build failed: $setupPath not found"
    }

    $setupInfo = Get-Item $setupPath
    Write-Host "Installer complete: $setupPath ($([math]::Round($setupInfo.Length / 1MB, 2)) MB)" -ForegroundColor Green
}
