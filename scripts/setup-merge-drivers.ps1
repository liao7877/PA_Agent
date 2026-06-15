# Register custom merge drivers for Trading Agent fork (run once per clone).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

git config --local merge.ours.name "keep ours (Trading Agent)"
git config --local merge.ours.driver "true"
git config --local merge.theirs.name "keep theirs (upstream)"
git config --local merge.theirs.driver "true"

Write-Host "已配置 merge drivers: ours / theirs" -ForegroundColor Green
Write-Host "建议同时执行: git config --local rerere.enabled true"
