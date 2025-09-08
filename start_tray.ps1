$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$venvPython = Join-Path $scriptDir ".\.venv\Scripts\python.exe"
$trayScript = Join-Path $scriptDir "tray_app.py"
$logFile = Join-Path $scriptDir "tray.log"

if (-not (Test-Path $venvPython)) {
    Write-Error "venv Python wurde nicht gefunden: $venvPython`nBitte erstelle ein virtuelles Environment oder passe den Pfad an."
    exit 1
}

Write-Host "Starte Tray-App (im Hintergrund). Logs: $logFile"
Start-Process -FilePath $venvPython -ArgumentList $trayScript -RedirectStandardOutput $logFile -RedirectStandardError $logFile -NoNewWindow -WindowStyle Hidden -PassThru
