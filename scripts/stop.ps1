# Stop Flightdeck by the PID recorded at spawn, and only that PID.
#
# Two identity checks before killing anything: the process image must be our venv
# python, and it must not predate the pidfile. If either fails the pidfile is stale
# and we refuse rather than guess. Never match on command line.

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repo    = Split-Path -Parent $PSScriptRoot
$python  = Join-Path $repo '.venv\Scripts\python.exe'
$pidFile = Join-Path $repo 'var\run\flightdeck.pid'

if (-not (Test-Path $pidFile)) {
    Write-Host 'Not running (no pidfile).'
    return
}

$recorded = (Get-Content $pidFile -Raw).Trim()
$procId = 0
if (-not [int]::TryParse($recorded, [ref]$procId)) {
    Write-Warning "Pidfile contains '$recorded', not a pid. Removing it."
    Remove-Item $pidFile -Force
    return
}

$proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
if (-not $proc) {
    Write-Host "Process $procId is already gone. Clearing stale pidfile."
    Remove-Item $pidFile -Force
    return
}

if ($proc.Path -ne $python) {
    Write-Warning "Pid $procId is '$($proc.Path)', not $python. Refusing to kill it."
    Write-Warning 'Stale pidfile. Delete it manually once you have confirmed what that pid is.'
    return
}

$pidFileWritten = (Get-Item $pidFile).LastWriteTime
if ($proc.StartTime -lt $pidFileWritten.AddMinutes(-1)) {
    Write-Warning "Pid $procId started $($proc.StartTime), before the pidfile was written $pidFileWritten."
    Write-Warning 'That is a recycled pid. Refusing to kill it.'
    return
}

Stop-Process -Id $procId -Force
Remove-Item $pidFile -Force
Write-Host "Stopped Flightdeck (pid $procId)."
