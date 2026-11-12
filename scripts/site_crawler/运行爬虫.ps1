param(
    [ValidateSet('http', 'browser', 'replay')][string]$Mode = 'http',
    [ValidateSet('all','21cnjy','jyeoo','chujuan','tiku')][string]$Site = 'tiku',
    [int]$Limit = 5,
    [int]$Pages = 1,
    [switch]$InteractiveLogin
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$bundledRoot = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies'
$pythonExe = Join-Path $bundledRoot 'python/python.exe'
$nodeExe = Join-Path $bundledRoot 'node/bin/node.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { $pythonExe = 'python' }
if (-not (Test-Path -LiteralPath $nodeExe)) { $nodeExe = 'node' }
$runPath = Join-Path $projectRoot ('data/site_crawl_runs/run_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
if ($Mode -eq 'http') {
    if ($Site -eq 'all') { throw 'HTTP模式请指定单站。四站登录采集请使用browser模式。' }
    & $pythonExe (Join-Path $PSScriptRoot 'edumath_crawler.py') http --config (Join-Path $PSScriptRoot 'tasks.json') --site $Site --limit $Limit --pages $Pages --out $runPath --automatic-only
} elseif ($Mode -eq 'browser') {
    $loginArgs = @()
    if ($InteractiveLogin) { $loginArgs = @('--login') }
    & $nodeExe (Join-Path $PSScriptRoot 'browser_crawler.mjs') --config (Join-Path $PSScriptRoot 'tasks.json') --site $Site --limit $Limit --pages $Pages --out $runPath @loginArgs --python $pythonExe
} else {
    & $pythonExe (Join-Path $PSScriptRoot 'edumath_crawler.py') import (Join-Path $projectRoot 'data/site_crawl_runs/20261022_fully_automatic_tiku/manifest.json') --out $runPath --automatic-only
}
if ($LASTEXITCODE -ne 0) { throw "采集未完全完成，退出码$LASTEXITCODE。请查看输出目录中的events.jsonl或manifest.json。" }
Write-Host "输出目录：$runPath"
