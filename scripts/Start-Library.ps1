$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$env:DEBUG = 'false'
$env:PYTHONUTF8 = '1'
docker compose up -d db
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -m scripts.dev
exit $LASTEXITCODE