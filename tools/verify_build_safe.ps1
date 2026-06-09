# Scan PyInstaller output for accidental inclusion of developer secrets.
param(
    [string]$DistDir = (Join-Path (Split-Path -Parent $PSScriptRoot) "dist\PA_Agent")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $DistDir)) {
    throw "Dist directory not found: $DistDir"
}

$forbiddenFiles = @(
    "settings.json",
    "license_private.pem",
    "secret.key"
)

$forbiddenDirs = @(
    "records",
    "logs",
    "experience"
)

foreach ($name in $forbiddenFiles) {
    $hits = Get-ChildItem -Path $DistDir -Recurse -Filter $name -File -ErrorAction SilentlyContinue
    if ($hits) {
        throw "Forbidden file packaged: $($hits.FullName -join ', ')"
    }
}

foreach ($dir in $forbiddenDirs) {
    $hits = Get-ChildItem -Path $DistDir -Recurse -Directory -Filter $dir -ErrorAction SilentlyContinue
    if ($hits) {
        throw "Forbidden directory packaged: $($hits.FullName -join ', ')"
    }
}

$patterns = @(
    "sk-[A-Za-z0-9]{16,}",
    "access_token=[A-Za-z0-9]{20,}",
    "SEC[A-Za-z0-9]{20,}",
    "BEGIN PRIVATE KEY",
    "api\.deepseek\.com/v1/chat/completions"
)

$textFiles = Get-ChildItem -Path $DistDir -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -match '^\.(json|txt|log|env|pem|key|ini|cfg|xml)$' -or $_.Name -match 'settings' }

foreach ($file in $textFiles) {
  try {
    $content = Get-Content -Path $file.FullName -Raw -ErrorAction Stop
  } catch {
    continue
  }
  foreach ($pattern in $patterns) {
    if ($content -match $pattern) {
      throw "Suspicious content ($pattern) in $($file.FullName)"
    }
  }
}

Write-Host "Build safety check passed: $DistDir"
