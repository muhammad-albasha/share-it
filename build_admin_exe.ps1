# Build helper: creates a single-file EXE for admin_desktop.py using PyInstaller
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# Prefer a clean venv named .venv_clean; fall back to .venv if .venv_clean is not present

# Use only .venv (mandatory)
$venvPython = Join-Path $scriptDir ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
	Write-Error "Required virtual environment '.venv' not found at: $venvPython`nPlease create it and install requirements (python -m venv .venv; .\.venv\Scripts\Activate; pip install -r requirements.txt)." ; exit 1
}

Write-Host "Using .venv python: $venvPython"
Write-Host "Upgrading pip and installing build deps in .venv..."
& $venvPython -m pip install --upgrade pip setuptools wheel
& $venvPython -m pip install pyinstaller pywebview requests

# Ensure assets exist
if (-not (Test-Path (Join-Path $scriptDir 'templates'))) { Write-Warning "templates/ not found — include your templates folder before packaging." }
if (-not (Test-Path (Join-Path $scriptDir 'static'))) { Write-Warning "static/ not found — include your static assets before packaging." }

Write-Host "Building admin_desktop.exe via PyInstaller (spec: admin_desktop.spec) using: $venvPython"

# Stop any running admin_desktop processes to avoid file locks
Write-Host "Stopping running admin_desktop processes (if any)..."
Get-Process -Name admin_desktop -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "Stopping process Id=$($_.Id)"; Stop-Process -Id $_.Id -Force }

# Remove existing dist folder so PyInstaller can recreate it (fail if locked)
$distDir = Join-Path $scriptDir 'dist\admin_desktop'
if (Test-Path $distDir) {
	Write-Host "Removing existing dist folder: $distDir"
	try {
		Remove-Item -Recurse -Force $distDir -ErrorAction Stop
	} catch {
		Write-Warning "Could not remove $distDir automatically. Ensure no process is using files inside and try again. Error: $_"
		Write-Error "PyInstaller failed due to locked files. Close running instances of admin_desktop.exe and re-run the script."; exit 1
	}
}

& $venvPython -m PyInstaller --noconfirm admin_desktop.spec

if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed with exit code $LASTEXITCODE"; exit $LASTEXITCODE }

Write-Host "Build finished. Check the 'dist\\admin_desktop' folder for the built application." 
