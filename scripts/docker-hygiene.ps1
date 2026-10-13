# NagarVault weekly Docker hygiene (Phase G of the storage-optimization plan).
#
# SAFE BY CONSTRUCTION:
#   * prunes the build cache (older than 7 days), dangling images, and exited
#     NON-k3d containers
#   * NEVER touches volumes - all k3d mission state lives there
#   * never removes k3d-managed containers even when exited (k3d owns their state)
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File docker-hygiene.ps1 [-Quiet]
param([switch]$Quiet)
$ErrorActionPreference = 'Continue'
$log = Join-Path $env:TEMP 'docker-hygiene.log'
function Log($m) {
  Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m)
  if (-not $Quiet) { Write-Host $m }
}

# Engine-up gate MUST use the exit code, not output presence: under a dead
# endpoint docker.exe still prints its error banner on stdout (52 lines), so
# an output-based test never detects a down engine (proven in verification).
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Log "engine down; aborting this run (nothing pruned)"; exit 1 }

Log "=== hygiene run start ==="
Log ((docker system df | Out-String).Trim())

# build cache older than 7 days (keeps warm cache useful between missions)
Log "builder prune (until=168h): $((docker builder prune -f --filter 'until=168h' 2>&1 | Select-Object -Last 1))"

# dangling images only (untagged, unreferenced - never tagged/pinned layers)
Log "dangling image prune: $((docker image prune -f 2>&1 | Select-Object -Last 1))"

# exited containers EXCLUDING anything k3d-managed (k3d names are always
# 'k3d-*' prefixed; docker inspect returns a leading slash - strip it and
# prefix-match, so e.g. 'my-nonk3d-app' is NOT falsely protected)
$removed = 0
foreach ($id in @(docker ps -aq --filter status=exited 2>$null)) {
  $name = (docker inspect $id --format '{{.Name}}' 2>$null).TrimStart('/')
  if ($name -like 'k3d*') { continue }
  docker rm $id | Out-Null
  $removed++
}
Log "exited non-k3d containers removed: $removed"

# NEVER run here: docker volume prune, docker system prune --volumes, or any
# operation naming volumes - the k3d mission state lives exclusively in volumes.

Log ((docker system df | Out-String).Trim())
Log "=== hygiene run end ==="
