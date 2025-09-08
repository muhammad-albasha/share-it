# Stops the Share-It FastAPI backend started by start-backend.ps1
# Prefers uvicorn.meta.json (listening PID), then uvicorn.pid,
# then discovers the process by listening port or command line if needed.

[CmdletBinding()]
param(
  [int]$Port = 8000,
  # Stop all matching processes if more than one is found (use with care)
  [switch]$All,
  # Do not kill; only print what would be stopped
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$pidFile  = Join-Path $root "uvicorn.pid"
$metaFile = Join-Path $root "uvicorn.meta.json"

$targetPid = $null
if (Test-Path $metaFile) {
  try {
    $meta = Get-Content $metaFile | ConvertFrom-Json
    if ($meta.listenPid) { $targetPid = [int]$meta.listenPid }
  } catch {}
}

if (-not $targetPid) {
  if (-not (Test-Path $pidFile)) {
    Write-Host "No PID meta/file found (uvicorn.meta.json / uvicorn.pid). Trying discovery…" -ForegroundColor Yellow
  } else {
    $targetPid = Get-Content $pidFile | Select-Object -First 1
  }
}

# If still no PID, try to discover by port and command line
if (-not $targetPid) {
  $candidatePids = @()
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -ne $null }
    if ($conns) {
      $candidatePids = $conns | Group-Object OwningProcess | ForEach-Object { [int]$_.Name }
    }
  } catch {}
  if (-not $candidatePids -or $candidatePids.Count -eq 0) {
    try {
      $ns = netstat -ano | Select-String -Pattern (":$Port\b")
      if ($ns) {
        $candidatePids = @(($ns | ForEach-Object { ($_ -split "\s+")[-1] }) | Select-Object -Unique | ForEach-Object { [int]$_ })
      }
    } catch {}
  }

  # Filter candidates to likely uvicorn/app:app processes
  $filtered = @()
  foreach ($pid in $candidatePids) {
    try {
      $p = Get-CimInstance Win32_Process -Filter "ProcessId=$pid" -ErrorAction SilentlyContinue
      if ($p -and $p.CommandLine -and ($p.CommandLine -match 'uvicorn') -and ($p.CommandLine -match 'app:app')) {
        $filtered += [int]$pid
      }
    } catch {}
  }
  if ($filtered.Count -gt 0) { $candidatePids = $filtered }

  if ($candidatePids.Count -ge 1) {
    if ($All) {
      Write-Host ("Found {0} candidate(s) on port {1}: {2}" -f $candidatePids.Count, $Port, ($candidatePids -join ', ')) -ForegroundColor Yellow
      foreach ($pid in $candidatePids) {
        if ($DryRun) {
          Write-Host "Would stop PID $pid" -ForegroundColor Yellow
        } else {
          try { Stop-Process -Id $pid -Force -ErrorAction Stop; Write-Host "Stopped PID $pid" -ForegroundColor Green } catch {}
        }
      }
      if (-not $DryRun) {
        if (Test-Path $pidFile)  { Remove-Item $pidFile  -Force -ErrorAction SilentlyContinue }
        if (Test-Path $metaFile) { Remove-Item $metaFile -Force -ErrorAction SilentlyContinue }
      }
      exit 0
    } else {
      $targetPid = $candidatePids[0]
      Write-Host ("Selected candidate PID {0} on port {1}" -f $targetPid, $Port) -ForegroundColor Yellow
    }
  }
}

if (-not $targetPid) {
  Write-Host "No PID available to stop." -ForegroundColor Yellow
  exit 0
}

try {
  $proc = Get-Process -Id $targetPid -ErrorAction Stop
  Write-Host "Stopping process PID $targetPid..." -ForegroundColor Yellow
  Stop-Process -Id $targetPid -Force
  if (Test-Path $pidFile)  { Remove-Item $pidFile  -Force -ErrorAction SilentlyContinue }
  if (Test-Path $metaFile) { Remove-Item $metaFile -Force -ErrorAction SilentlyContinue }
  Write-Host "Stopped." -ForegroundColor Green
} catch {
  Write-Host "Process $targetPid not found. Cleaning up PID/meta files." -ForegroundColor Yellow
  if (Test-Path $pidFile)  { Remove-Item $pidFile  -Force -ErrorAction SilentlyContinue }
  if (Test-Path $metaFile) { Remove-Item $metaFile -Force -ErrorAction SilentlyContinue }
}
