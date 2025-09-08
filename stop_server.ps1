param(
    [switch]$Force
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pidFile = Join-Path $scriptDir "server.pid"
$logFile = Join-Path $scriptDir "server.log"

if (-not (Test-Path $pidFile)) {
    Write-Host "Keine PID-Datei gefunden ($pidFile). Versuche, uvicorn/python-Prozesse im Projektverzeichnis zu finden..." -ForegroundColor Yellow

    # Suche Win32-Prozesse mit CommandLine-Info (uvicorn oder app:app) oder Python aus diesem Verzeichnis
    $candidates = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.CommandLine -and ($_.CommandLine -match 'uvicorn' -or $_.CommandLine -match 'app:app')) -or
        ($_.ExecutablePath -and ($_.ExecutablePath -match 'python.exe') -and ($_.CommandLine -and $_.CommandLine -match ([regex]::Escape($scriptDir))))
    }

    if (-not $candidates -or $candidates.Count -eq 0) {
        Write-Host "Keine passenden Prozesse gefunden. Verwende '-Force' um breiter zu suchen." -ForegroundColor Yellow
        if (-not $Force) { exit 0 }
    }

    if ($candidates -and $candidates.Count -gt 0) {
        Write-Host "Gefundene Prozesse zur Beendigung:"
        $candidates | Select-Object ProcessId, Name, CommandLine | ForEach-Object { Write-Host "PID=$($_.ProcessId) Name=$($_.Name) Cmd=$($_.CommandLine)" }
        Write-Host "Beende gefundene Prozesse..."
        foreach ($proc in $candidates) {
            try {
                Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
                Write-Host "Prozess $($proc.ProcessId) gestoppt."
            } catch {
                Write-Host "Konnte Prozess $($proc.ProcessId) nicht stoppen: $_" -ForegroundColor Red
            }
        }
    }

    if (-not $Force) { exit 0 }
}

$targetPid = Get-Content $pidFile -ErrorAction SilentlyContinue
if (-not $targetPid) {
    Write-Host "PID-Datei war leer; lösche Datei." -ForegroundColor Yellow
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    exit 0
}

$intPid = [int]$targetPid
try {
    $p = Get-Process -Id $intPid -ErrorAction Stop
    Write-Host "Stopping process PID $intPid..."
    # Try to stop the main process
    $p | Stop-Process -Force -ErrorAction SilentlyContinue

    # Ensure child processes are terminated too (taskkill /T /F)
    try {
        & cmd.exe /c "taskkill /PID $intPid /T /F" > $null 2>&1
        Write-Host "taskkill executed for PID $intPid (child processes terminated)."
    } catch {
        Write-Host "taskkill failed or not available: $_" -ForegroundColor Yellow
    }

    Write-Host "Prozess $intPid gestoppt."
} catch {
    Write-Host "Prozess mit PID $intPid nicht gefunden. Entferne PID-Datei." -ForegroundColor Yellow
}

Remove-Item $pidFile -ErrorAction SilentlyContinue
Write-Host "PID-Datei entfernt. Letzte Log-Zeilen ($logFile):"
if (Test-Path $logFile) {
    Get-Content $logFile -Tail 50
} else {
    Write-Host "Keine Log-Datei gefunden." -ForegroundColor Yellow
}
