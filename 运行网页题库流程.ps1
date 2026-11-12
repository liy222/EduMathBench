param(
  [ValidateSet('trial','login-capture','collect','reparse','select','assets','variants','replay','verify','build','review','status')]
  [string]$Mode='verify',
  [int]$Budget=500
)
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
$taskPython=Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython='python' }
$env:PYTHONIOENCODING='utf-8'
Push-Location -LiteralPath $taskRoot
try {
  & $taskPython (Join-Path $taskRoot 'scripts\edumath_web.py') $Mode --budget $Budget
  if ($LASTEXITCODE -ne 0) { throw "流程未通过，请查看错误与data/benchmark_web_v0.2/reports。" }
} finally { Pop-Location }
