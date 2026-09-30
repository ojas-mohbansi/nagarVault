# NagarVault weekly Docker hygiene (Phase G of the storage-optimization plan).
#
# SAFE BY CONSTRUCTION:
#   * prunes the build cache (older than 7 days), dangling images, and exited
#     NON-k3d containers
#   * NEVER touches volumes - all k3d mission state lives there
#   * never removes k3d-managed containers even when exited (k3d-nagar-tools is
#     legitimately stoppable state; k3d owns its node containers)
#   * if the engine is down, starts Docker Desktop and aborts politely if it
#     does not come up (never compact/prune blind)
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File docker-hygiene.ps1 [-Quiet]
param([switch]$Quiet)
$ErrorActionPreference = 'Continue'
$log = Join-Path $env:TEMP 'docker-hygiene.log'
function Log($m) {
  Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m)
  if (-not $Quiet) { Write-Host $m }
}

# 0. engine must be up
if (-not (docker info 2>$null)) {
  Log "engine down; attempting Docker Desktop start"
  Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
  $up = $false
  for ($i = 0; $i -lt 30; $i++) { Start-Sleep 10; if (docker info 2>$null) { $up = $true; break } }
  if (-not $up) { Log "engine did not come up; aborting this run (nothing pruned)"; exit 1 }
}

Log "=== hygiene run start ==="
Log ((docker system df | Out-String).Trim())

# 1. build cache older than 7 days (keeps warm cache useful between missions)
$out = (docker builder prune -f --filter "until=168h" 2>&1 | Select-Object -Last 1)
Log "builder prune (until=168h): $out"

# 2. dangling images only (untagged, unreferenced - never tagged/pinned layers)
$out = (docker image prune -f 2>&1 | Select-Object -Last 1)
Log "dangling image prune: $out"

# 3. exited containers EXCLUDING anything k3d-managed
$ids = @(docker ps -aq --filter status=exited 2>$null)
$removed = 0
foreach ($id in $ids) {
  $name = docker inspect $id --format '{{.Name}}' 2>$null
  if ($name -like '*k3d*') { Log "keeping exited k3d container $name (stateful)"; continue }
  docker rm $id | Out-Null
  $removed++
}
Log "exited non-k3d containers removed: $removed"

# NEVER run here: docker volume prune, docker system prune --volumes, or any
# operation naming volumes - the k3d mission state lives exclusively in volumes.

Log ((docker system df | Out-String).Trim())
Log "=== hygiene run end ==="
