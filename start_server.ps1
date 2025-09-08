param(
    [int]$Port = 8000,
    [string]$BindHost = "0.0.0.0"
)

# Pfade
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$venvPython = Join-Path $scriptDir ".\.venv\Scripts\python.exe"
$venvPythonW = Join-Path $scriptDir ".\.venv\Scripts\pythonw.exe"
$pidFile = Join-Path $scriptDir "server.pid"
$logFile = Join-Path $scriptDir "server.log"
$errLogFile = Join-Path $scriptDir "server.log.err"

if (-not (Test-Path $venvPython)) {
    Write-Error "venv Python wurde nicht gefunden: $venvPython`nBitte erstelle ein virtuelles Environment oder passe den Pfad an."
    exit 1
}

if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Es scheint bereits ein Server-Prozess mit PID $existing zu existieren. Entferne $pidFile, falls der Prozess nicht mehr läuft." -ForegroundColor Yellow
        exit 1
    }
}

$args = "-m uvicorn app:app --host $BindHost --port $Port"
Write-Host "Starte Server: $venvPython $args"

# Verwende pythonw.exe aus dem venv wenn vorhanden (versteckt Fenster)
if (Test-Path $venvPythonW) {
    $serverPython = $venvPythonW
} else {
    $serverPython = $venvPython
}

# Starten und stdout/stderr in separate Log files umleiten
$proc = Start-Process -FilePath $serverPython -ArgumentList $args -RedirectStandardOutput $logFile -RedirectStandardError $errLogFile -PassThru

if ($null -eq $proc) {
    Write-Error "Start-Process fehlgeschlagen."
    exit 1
}

 $proc.Id | Out-File -FilePath $pidFile -Encoding ascii
Write-Host "Server gestartet (PID $($proc.Id)). Logs: $logFile (stdout), $errLogFile (stderr). PID-Datei: $pidFile"

Write-Host "Letzte Log-Zeilen (stdout):"
if (Test-Path $logFile) { Get-Content $logFile -Tail 50 }
Write-Host "Letzte Log-Zeilen (stderr):"
if (Test-Path $errLogFile) { Get-Content $errLogFile -Tail 50 }

# Zusätzlich Tray-App starten (falls vorhanden)
$trayScript = Join-Path $scriptDir "tray_app.py"
$trayLog = Join-Path $scriptDir "tray.log"
$trayErrLog = Join-Path $scriptDir "tray.log.err"
if (Test-Path $trayScript) {
    try {
        if (Test-Path $venvPythonW) {
            Start-Process -FilePath $venvPythonW -ArgumentList $trayScript -RedirectStandardOutput $trayLog -RedirectStandardError $trayErrLog -PassThru | Out-Null
        } else {
            Start-Process -FilePath $venvPython -ArgumentList $trayScript -RedirectStandardOutput $trayLog -RedirectStandardError $trayErrLog -PassThru | Out-Null
        }
        Write-Host "Tray-App gestartet (Logs: $trayLog, $trayErrLog)"
    } catch {
        Write-Host "Konnte Tray-App nicht starten: $_" -ForegroundColor Yellow
    }
}
