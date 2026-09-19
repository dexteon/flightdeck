# Start Flightdeck as a hidden background process.
#
# Records the PID at spawn from -PassThru. stop.ps1 kills only that id, never a
# command-line substring match: "uvicorn" and "server.py" are the most common entry
# points on this box and a substring match has killed unrelated live servers before.

[CmdletBinding()]
param(
    [int]$Port = 9310,
    [string]$BindHost = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'

$repo    = Split-Path -Parent $PSScriptRoot
$python  = Join-Path $repo '.venv\Scripts\python.exe'
$server  = Join-Path $repo 'server'
$pidFile = Join-Path $repo 'var\run\flightdeck.pid'
$outLog  = Join-Path $repo 'var\logs\server.out.log'
$errLog  = Join-Path $repo 'var\logs\server.err.log'

if (-not (Test-Path $python)) {
    throw "No virtualenv at $python. Run: uv venv --python 3.12; uv pip install -e `".[dev]`""
}

New-Item -ItemType Directory -Force -Path (Split-Path $pidFile) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $outLog)  | Out-Null

if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile -ErrorAction SilentlyContinue
    $proc = Get-Process -Id $existing -ErrorAction SilentlyContinue
    if ($proc -and $proc.Path -eq $python) {
        Write-Host "Already running (pid $existing) at http://${BindHost}:${Port}"
        return
    }
    Remove-Item $pidFile -Force
}

$env:PYTHONPATH = $server

$p = Start-Process -FilePath $python `
    -ArgumentList '-m', 'uvicorn', 'flightdeck.main:app', '--host', $BindHost, '--port', $Port `
    -WorkingDirectory $server `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError  $errLog

$p.Id | Set-Content -Path $pidFile -Encoding ascii
Write-Host "Flightdeck started (pid $($p.Id)) at http://${BindHost}:${Port}"
Write-Host "Logs: $outLog"
