# Starts the Share-It FastAPI backend via uvicorn
# Usage examples:
#   .\start-backend.ps1
#   .\start-backend.ps1 -Host 0.0.0.0 -Port 8000 -LogLevel info
#   .\start-backend.ps1 -Detach   # run in background

[CmdletBinding()]
param(
    [Alias('Host')]
    [string]$BindAddress = "0.0.0.0",
    [Alias('Port')]
    [int]$BindPort = 8000,
    [ValidateSet('critical','error','warning','info','debug','trace')]
    [string]$LogLevel = "info",
    [switch]$Detach,
    # Run with no visible console window (uses pythonw if available, else Hidden window)
    [switch]$NoConsole,
    # Window style when Detach is used and a window is created
    [ValidateSet('Normal','Minimized','Hidden')]
    [string]$WindowStyle = 'Minimized',
    # Optional log file path to capture stdout/stderr when Detach-ing
    [string]$LogFile
)

$ErrorActionPreference = "Stop"

# Go to repo root
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Resolve Python in venv or fallback to system
$venvPython  = Join-Path $root ".venv\\Scripts\\python.exe"
$venvPythonW = Join-Path $root ".venv\\Scripts\\pythonw.exe"
$python      = if (Test-Path $venvPython)  { $venvPython }  else { "python" }
$pythonw     = if (Test-Path $venvPythonW) { $venvPythonW } else { "pythonw" }
if ($python -eq 'python') {
    Write-Host "Virtualenv Python not found, using system python." -ForegroundColor Yellow
}

# Ensure pip is available
try {
    & $python -m pip --version | Out-Null
} catch {
    Write-Host "Bootstrapping pip (ensurepip)…" -ForegroundColor Yellow
    & $python -m ensurepip --upgrade
}

# Install dependencies if uvicorn is missing
$needInstall = $false
try {
    & $python -c "import uvicorn" 2>$null
} catch {
    $needInstall = $true
}
if ($needInstall) {
    Write-Host "Installing requirements…" -ForegroundColor Cyan
    & $python -m pip install --upgrade pip
    & $python -m pip install -r (Join-Path $root "requirements.txt")
}

# Ensure storage dir exists
$storage = Join-Path $root "storage"
if (-not (Test-Path $storage)) { New-Item -ItemType Directory -Path $storage | Out-Null }

$argsList = @("-m","uvicorn","app:app","--host",$BindAddress,"--port",$BindPort.ToString(),"--log-level",$LogLevel)

if ($Detach) {
    Write-Host "Starting Share-It API in background…" -ForegroundColor Green
    # Choose interpreter and window style based on console preference
    $exe = $python
    $ws  = [System.Diagnostics.ProcessWindowStyle]::$WindowStyle

    if ($NoConsole) {
        # If a log file is requested, prefer console python with hidden window so redirection works
        if ($LogFile) {
            $ws = [System.Diagnostics.ProcessWindowStyle]::Hidden
        } else {
            # Prefer pythonw.exe if available (venv or system)
            $sysPythonw = $null
            try { $sysPythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Path } catch {}
            if (Test-Path $venvPythonW)      { $exe = $venvPythonW }
            elseif ($sysPythonw)             { $exe = $sysPythonw }
            else {
                $exe = $python
            }
            # Hide the window if we fall back to console python
            $ws = [System.Diagnostics.ProcessWindowStyle]::Hidden
        }
    }

    # Build Start-Process parameters
    $spArgs = @{
        FilePath     = $exe
        ArgumentList = $argsList
        WindowStyle  = $ws
        PassThru     = $true
    }
    # Only attempt redirection when using console python (not pythonw)
    if ($LogFile -and ($exe -ne $venvPythonW)) {
        if (-not [System.IO.Path]::IsPathRooted($LogFile)) { $LogFile = Join-Path $root $LogFile }
        $logDir = Split-Path -Parent $LogFile
        if ($logDir -and -not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
        $stdOut = $LogFile
        $stdErr = "$LogFile.err"
        $spArgs.RedirectStandardOutput = $stdOut
        $spArgs.RedirectStandardError  = $stdErr
    } elseif ($LogFile) {
        Write-Host "Note: LogFile ignored when using pythonw.exe (no stdout/stderr)." -ForegroundColor Yellow
    }

    $proc = Start-Process @spArgs
    # Try to resolve the actual listening PID for the chosen port
    $listenPid = $null
    try {
        # Give the server a moment to bind
        Start-Sleep -Milliseconds 800
        $conn = Get-NetTCPConnection -LocalPort $BindPort -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            $listenPid = ($conn | Select-Object -First 1).OwningProcess
        }
    } catch {}
    if (-not $listenPid) {
        try {
            $ns = netstat -ano | Select-String -Pattern (":$BindPort\b")
            if ($ns) {
                $line = ($ns | Select-Object -First 1).Line
                # PID is the last whitespace-separated token
                $listenPid = ($line -split "\s+")[-1]
            }
        } catch {}
    }

    $pidFile = Join-Path $root "uvicorn.pid"
    $metaFile = Join-Path $root "uvicorn.meta.json"
    $pidToStore = if ($listenPid) { $listenPid } else { $proc.Id }
    $pidToStore | Out-File -FilePath $pidFile -Encoding ascii -Force

    $meta = @{
        parentPid = $proc.Id
        listenPid = $listenPid
        port      = $BindPort
        address   = $BindAddress
        started   = (Get-Date).ToString('s')
        logLevel  = $LogLevel
    }
    $meta | ConvertTo-Json | Out-File -FilePath $metaFile -Encoding ascii -Force

    $shownPid = if ($listenPid) { $listenPid } else { $proc.Id }
    Write-Host ("Started. PID {0}. PID saved to {1}" -f $shownPid, $pidFile) -ForegroundColor Green
    exit 0
}
else {
    Write-Host ("Starting Share-It API on http://{0}:{1} (log-level: {2})" -f $BindAddress,$BindPort,$LogLevel) -ForegroundColor Green
    & $python @argsList
}
