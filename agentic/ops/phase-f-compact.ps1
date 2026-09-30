# Phase F - one-time docker_data.vhdx compaction (diskpart fallback; Optimize-VHD unavailable).
# Sequence: graceful Docker Desktop stop -> wsl shutdown -> attach readonly + compact + detach
# -> record sizes -> restart Docker Desktop. Writes a done-marker for detached polling.
# Administrator privileges required (diskpart vdisk operations).
$ErrorActionPreference = 'Stop'
$log  = 'C:\Users\styli\AppData\Local\Temp\phase-f-compaction.log'
$done = 'C:\Users\styli\AppData\Local\Temp\phase-f-compaction.done'
$vhdx = 'C:\Users\styli\AppData\Local\Docker\wsl\disk\docker_data.vhdx'
$dp   = 'C:\Users\styli\AppData\Local\Temp\phase-f-diskpart.txt'

function Log($m) { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format 'HH:mm:ss'), $m) }

if (Test-Path $done) { Remove-Item $done -Force }
Remove-Item $log -Force -ErrorAction SilentlyContinue

$before = (Get-Item $vhdx).Length
Log "START before-bytes=$before"

# 1. Graceful Docker Desktop shutdown
$dd = Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue
if ($dd) { Log "stopping Docker Desktop (pid $($dd.Id))"; $dd | Stop-Process -Force; Start-Sleep -Seconds 5 }
Get-Process 'com.docker.backend' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# 2. Shut WSL down so the VHDX is detached
wsl.exe --shutdown
Start-Sleep -Seconds 5
Log "wsl shutdown complete"

# 3. Compact via diskpart (attach readonly -> compact -> detach)
@"
select vdisk file="$vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
"@ | Set-Content -Path $dp -Encoding ASCII

Log "diskpart compact starting"
& diskpart /s $dp *>> $log
Log "diskpart exit=$LASTEXITCODE"

$after = (Get-Item $vhdx).Length
Log "DONE before=$before after=$after reclaimed=$($before - $after)"

# 4. Bring Docker Desktop back
Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
Log "docker desktop restart requested"
New-Item -ItemType File -Path $done -Force | Out-Null
