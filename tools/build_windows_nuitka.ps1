# Build PA Agent with Nuitka (recommended release backend).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools/build_windows_nuitka.ps1
#   powershell -ExecutionPolicy Bypass -File tools/build_windows_nuitka.ps1 -SkipTests

param(
    [switch]$SkipTests,
    [switch]$SkipInstall,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-PythonReady {
    $versionText = & python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python not found. Install Python 3.11+ and ensure 'python' is on PATH."
    }
    Write-Host "Python: $versionText"
}

function Remove-NuitkaArtifacts {
    $targets = @(
        (Join-Path $Root "dist\PA_Agent"),
        (Join-Path $Root "dist\PA_Agent.nuitka"),
        (Join-Path $Root "run.build"),
        (Join-Path $Root "run.dist"),
        (Join-Path $Root "run.onefile-build")
    )
    foreach ($path in $targets) {
        if (Test-Path $path) {
            Write-Host "Removing $path"
            Remove-Item -Recurse -Force $path
        }
    }
}

Write-Step "PA Agent Nuitka build"
Assert-PythonReady

if ($Clean) {
    Write-Step "Cleaning previous Nuitka artifacts"
    Remove-NuitkaArtifacts
}

Write-Step "Syncing embedded public key"
python tools/sync_embedded_pubkey.py
if ($LASTEXITCODE -ne 0) { throw "sync_embedded_pubkey failed" }

if (-not $SkipInstall) {
    Write-Step "Installing project dependencies"
    python -m pip install --upgrade pip
    python -m pip install -e .
    python -m pip install nuitka ordered-set zstandard
} else {
    Write-Step "Skipping pip install (-SkipInstall)"
    python -m pip install nuitka ordered-set zstandard
}

if (-not $SkipTests) {
    Write-Step "Running unit tests (tests/unit)"
    python -m pytest tests/unit/test_licensing.py tests/unit/test_local_tz.py -q
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed. Fix tests or pass -SkipTests to bypass."
    }
}

$licenseClient = Join-Path $Root "config\license_client.json"
if (-not (Test-Path $licenseClient)) {
    $licenseClient = Join-Path $Root "config\license_client.example.json"
}

$distDir = Join-Path $Root "dist\PA_Agent"
New-Item -ItemType Directory -Force -Path $distDir | Out-Null

Write-Step "Building with Nuitka"
$nuitkaArgs = @(
    "-m", "nuitka",
    "run.py",
    "--standalone",
    "--assume-yes-for-downloads",
    "--windows-console-mode=disable",
    "--enable-plugin=pyqt6",
    "--include-package=pa_agent",
    "--noinclude-data-files=pa_agent/licensing/public_key.pem",
    "--noinclude-data-files=*/public_key.pem",
    "--include-module=MetaTrader5",
    "--include-module=win32crypt",
    "--include-module=pywintypes",
    "--include-module=tiktoken_ext.openai_public",
    "--include-module=tiktoken_ext",
    "--include-data-dir=prompt_engineering=prompt_engineering",
    "--include-data-files=config/settings.example.json=config/settings.example.json",
    "--include-data-files=$licenseClient=config/license_client.json",
    "--include-data-files=pa_agent/gui/theme/dark.qss=pa_agent/gui/theme/dark.qss",
    "--output-dir=$distDir",
    "--output-filename=PA_Agent.exe",
    "--remove-output"
)

python @nuitkaArgs
if ($LASTEXITCODE -ne 0) {
    throw "Nuitka failed with exit code $LASTEXITCODE"
}

$exePath = Join-Path $distDir "PA_Agent.exe"
if (-not (Test-Path $exePath)) {
    # Nuitka standalone may place exe in run.dist subfolder
    $candidate = Get-ChildItem -Path $distDir -Recurse -Filter "PA_Agent.exe" -File | Select-Object -First 1
    if ($candidate) {
        if ($candidate.DirectoryName -ne $distDir) {
            Write-Host "Moving Nuitka output into dist/PA_Agent"
            Get-ChildItem -Path $candidate.Directory.FullName | ForEach-Object {
                Copy-Item -Recurse -Force $_.FullName (Join-Path $distDir $_.Name)
            }
        }
    }
}

if (-not (Test-Path $exePath)) {
    throw "Build failed: PA_Agent.exe not found under $distDir"
}

# Remove duplicate Nuitka subfolder after flattening
$runDist = Join-Path $distDir "run.dist"
if (Test-Path $runDist) {
    Write-Host "Removing leftover run.dist folder"
    Remove-Item -Recurse -Force $runDist
}

# Strip any accidentally bundled loose public keys
Get-ChildItem -Path $distDir -Recurse -Filter "public_key.pem" -File -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing bundled public key: $($_.FullName)"
        Remove-Item -Force $_.FullName
    }

Write-Step "Verifying build does not contain private config"
powershell -ExecutionPolicy Bypass -File (Join-Path $Root "tools\verify_build_safe.ps1") -DistDir $distDir
if ($LASTEXITCODE -ne 0) {
    throw "Build safety check failed"
}

$exeInfo = Get-Item $exePath
Write-Host ""
Write-Host "Nuitka build complete." -ForegroundColor Green
Write-Host "  Exe     : $exePath"
Write-Host "  Size    : $([math]::Round($exeInfo.Length / 1MB, 2)) MB"
Write-Host "  Folder  : $distDir"
