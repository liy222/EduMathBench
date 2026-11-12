param(
 [ValidateSet('self-test','build','verify','viewer','run','score','batch-check','batch-run','pilot-report','image-check','prepare-followup')][string]$Action='self-test',
 [string]$Config='config/evaluation_template.json',
 [ValidateSet('debug','dev','test','all')][string]$Split='debug',
 [string]$Output='runs/local_debug',
 [string]$Manifest='config/evaluation_domestic_six.json',
 [switch]$Resume,
 [switch]$AllowTest
)
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
$pythonExecutable=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if(-not (Test-Path -LiteralPath $pythonExecutable)){$pythonExecutable=(Get-Command python -ErrorAction Stop).Source}
$commands=@{'self-test'='eval-self-test';'build'='reviewed-build';'verify'='reviewed-verify';'viewer'='reviewed-viewer';'run'='eval-run';'score'='eval-score';'batch-check'='eval-batch-check';'batch-run'='eval-batch-run';'pilot-report'='eval-pilot-report';'image-check'='eval-image-check';'prepare-followup'='eval-prepare-followup'}
$arguments=@((Join-Path $projectRoot 'scripts/edumath_web.py'),$commands[$Action])
if($Action -eq 'run'){$arguments+=@('--config',$Config,'--split',$Split,'--output',$Output);if($Resume){$arguments+='--resume'};if($AllowTest){$arguments+='--allow-test'}}
if($Action -eq 'score'){$arguments+=@('--run',$Output)}
if($Action -in @('batch-check','batch-run')){
 if(-not $PSBoundParameters.ContainsKey('Output')){$Output='runs/domestic_six_debug'}
 $arguments+=@('--manifest',$Manifest,'--output',$Output)
 if($Action -eq 'batch-run' -and $Resume){$arguments+='--resume'}
 if($AllowTest){$arguments+='--allow-test'}
}
if($Action -eq 'pilot-report'){
 if(-not $PSBoundParameters.ContainsKey('Output')){$Output='runs/domestic_six_debug'}
 $arguments+=@('--run',$Output)
}
if($Action -eq 'image-check' -and $PSBoundParameters.ContainsKey('Output')){$arguments+=@('--output',$Output)}
Push-Location -LiteralPath $projectRoot
try { $env:PYTHONIOENCODING='utf-8'; & $pythonExecutable @arguments; if($LASTEXITCODE -ne 0){throw "流程退出码：$LASTEXITCODE"} }
finally {Pop-Location}
