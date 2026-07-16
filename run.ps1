# CCUsageMonitor launcher: creates venv if needed, installs deps, runs the app.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv"
$py   = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "[run] Creating virtual environment..." -ForegroundColor Cyan
    py -m venv $venv
    & $py -m pip install --upgrade pip | Out-Null
    & $py -m pip install -r (Join-Path $root "requirements.txt")
}

$env:PYTHONPATH = Join-Path $root "src"
& $py -m ccmonitor @args
