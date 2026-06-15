# Merge upstream/main into trading-agent (Trading Agent fork workflow).
param(
    [switch]$NoTest,
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$branch = (git branch --show-current).Trim()
if ($branch -ne "trading-agent") {
    Write-Host "当前分支: $branch（期望 trading-agent）" -ForegroundColor Yellow
    $ans = Read-Host "是否继续 merge? (y/N)"
    if ($ans -notmatch '^[yY]') { exit 1 }
}

Write-Host "==> git fetch upstream" -ForegroundColor Cyan
git fetch upstream

$date = Get-Date -Format "yyyy-MM-dd"
Write-Host "==> git merge upstream/main" -ForegroundColor Cyan
git merge upstream/main -m "merge upstream/main $date"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "存在冲突。请按 docs/上游合并策略.md 处理 C 类文件后：" -ForegroundColor Yellow
    Write-Host "  git add -A && git commit" -ForegroundColor Yellow
    exit $LASTEXITCODE
}

if (-not $NoTest) {
    Write-Host "==> pytest tests/unit" -ForegroundColor Cyan
    python -m pytest tests/unit -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $NoPush) {
    Write-Host "==> git push origin HEAD" -ForegroundColor Cyan
    git push origin HEAD
}

Write-Host "合并完成。" -ForegroundColor Green
