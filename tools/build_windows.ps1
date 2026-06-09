# Build PA Agent Windows distributable with PyInstaller.
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools/build_windows.ps1
# Optional Inno Setup installer:
#   powershell -ExecutionPolicy Bypass -File tools/build_windows.ps1 -Installer

param(
    [switch]$Installer
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Ensuring build dependencies"
python -m pip install --upgrade pip
python -m pip install pyinstaller

if (Test-Path (Join-Path $Root "config\settings.json")) {
    Write-Host "Note: config\settings.json exists locally but will NOT be packaged (only settings.example.json)."
}

Write-Host "==> Building with PyInstaller"
python -m PyInstaller --noconfirm PA_Agent.spec

$DistDir = Join-Path $Root "dist\PA_Agent"
if (-not (Test-Path (Join-Path $DistDir "PA_Agent.exe"))) {
    throw "Build failed: PA_Agent.exe not found in $DistDir"
}

Write-Host "==> Verifying build does not contain private config"
powershell -ExecutionPolicy Bypass -File (Join-Path $Root "tools\verify_build_safe.ps1") -DistDir $DistDir

Write-Host "Build complete: $DistDir"

if ($Installer) {
    $Iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $Iscc) {
        throw "Inno Setup 6 not found. Install from https://jrsoftware.org/isinfo.php"
    }

    Write-Host "==> Building installer with Inno Setup"
    & $Iscc (Join-Path $Root "tools\installer.iss")
    Write-Host "Installer complete: $(Join-Path $Root 'dist\PA_Agent_Setup.exe')"
}
