# Report whether Flightdeck is running, and what /api/health says.

[CmdletBinding()]
param([int]$Port = 9310)

$ErrorActionPreference = 'Continue'

$repo    = Split-Path -Parent $PSScriptRoot
$python  = Join-Path $repo '.venv\Scripts\python.exe'
$pidFile = Join-Path $repo 'var\run\flightdeck.pid'

if (Test-Path $pidFile) {
    $procId = (Get-Content $pidFile -Raw).Trim()
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc -and $proc.Path -eq $python) {
        Write-Host "process : running (pid $procId, started $($proc.StartTime))"
    } elseif ($proc) {
        Write-Host "process : STALE pidfile (pid $procId is $($proc.Path))"
    } else {
        Write-Host "process : STALE pidfile (pid $procId is gone)"
    }
} else {
    Write-Host 'process : not running (no pidfile)'
}

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5
    Write-Host "hermes  : $($health.hermes.state) (writes_enabled=$($health.hermes.writes_enabled), token=$($health.hermes.token_source))"
    Write-Host "boards  : $($health.boards.available) of $($health.boards.total) reporting"
    foreach ($b in $health.boards.unavailable) { Write-Host "          unavailable: $($b.slug) - $($b.reason)" }
    $prints = $health.schema_fingerprints.PSObject.Properties | Group-Object { $_.Value }
    Write-Host "schema  : $($prints.Count) distinct fingerprint(s) across boards"
    foreach ($g in $prints) { Write-Host "          $($g.Name): $($g.Group.Name -join ', ')" }
    Write-Host "fts5    : $($health.fts5)"
} catch {
    Write-Host "api     : not answering on $Port ($($_.Exception.Message))"
}
