# Build a standalone, double-clickable CCUsageMonitor.exe (no console window).
# Output: dist\CCUsageMonitor.exe  — double-click it, or right-click > Pin to taskbar.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py   = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "[build] Creating venv + installing deps..." -ForegroundColor Cyan
    py -m venv (Join-Path $root ".venv")
    & $py -m pip install --upgrade pip | Out-Null
    & $py -m pip install -r (Join-Path $root "requirements.txt")
}
& $py -m pip install --quiet pyinstaller

# (Re)generate the icon so it stays in sync with the app's look.
$env:QT_QPA_PLATFORM = "offscreen"
& $py (Join-Path $root "tools\make_icon.py")
Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue

Write-Host "[build] Running PyInstaller..." -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm --clean `
    --windowed --onefile `
    --name CCUsageMonitor `
    --icon (Join-Path $root "assets\icon.ico") `
    --paths (Join-Path $root "src") `
    (Join-Path $root "launcher.py")

Write-Host ""
Write-Host "[build] Done -> dist\CCUsageMonitor.exe" -ForegroundColor Green
Write-Host "        Double-click it in Explorer, or right-click > Pin to taskbar." -ForegroundColor Green
