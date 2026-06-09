# Build PA Agent License Issuer as a standalone Windows exe.
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools/build_license_issuer.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Ensuring PyInstaller"
python -m pip install pyinstaller cryptography PyQt6 --quiet

Write-Host "==> Building License Issuer (onefile exe)"
python -m PyInstaller --noconfirm LicenseIssuer.spec

$ExePath = Join-Path $Root "dist\PA_Agent_License_Issuer.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build failed: $ExePath not found"
}

# Safety: issuer exe must not embed private key PEM content.
$bytes = [System.IO.File]::ReadAllBytes($ExePath)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
if ($text -match "BEGIN PRIVATE KEY") {
    throw "Safety check failed: private key material found inside issuer exe"
}

Write-Host "Build complete: $ExePath"
