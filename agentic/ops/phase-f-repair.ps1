# Phase F repair - after diskpart compaction left the VHDX attached and possibly
# with a regenerated GPT DiskId. Docker's wsl-bootstrap identifies its data disk by
# a WWID derived from the VHDX GPT DiskId (log: wwid ending adf0c0f03179b0a2751db2a3,
# i.e. GUID adf0c0f0-3179-dc48-9cfd-b0a2751db2a3 compacted).
$ErrorActionPreference = 'Continue'
$log  = 'C:\Users\styli\AppData\Local\Temp\phase-f-repair.log'
$done = 'C:\Users\styli\AppData\Local\Temp\phase-f-repair.done'
$vhdx = 'C:\Users\styli\AppData\Local\Docker\wsl\disk\docker_data.vhdx'
$want = 'adf0c0f0-3179-dc48-9cfd-b0a2751db2a3'
$dp   = 'C:\Users\styli\AppData\Local\Temp\phase-f-repair-dp.txt'

function Log($m) { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format 'HH:mm:ss'), $m) }
function Run-DiskPart($text) {
  Set-Content -Path $dp -Value $text -Encoding ASCII
  $out = & diskpart /s $dp 2>&1
  Add-Content -Path $log -Value ($out | Out-String)
  return $out
}

if (Test-Path $done) { Remove-Item $done -Force }
$before = (Get-Item $vhdx).Length
Log "START vhdx-bytes=$before"

# 1. Detach any leftover attachment (ignore 'not attached' errors)
Log "step1: detach leftover attachment"
Run-DiskPart @"
select vdisk file="$vhdx"
detach vdisk
"@

# 2. Attach readonly and read the GPT DiskId
Log "step2: attach readonly + read identity"
Run-DiskPart @"
select vdisk file="$vhdx"
attach vdisk readonly
"@
Start-Sleep -Seconds 2
$disk = Get-Disk | Where-Object { $_.BusType -eq 'File Backed Virtual' } | Select-Object -First 1
if (-not $disk) { Log "FATAL: vhdx disk not found after attach"; exit 1 }
$got = ("{0}" -f $disk.Guid).Trim('{}')
Log "current Guid=$got want=$want"

# 3. Restore the expected GPT DiskId if it differs
if ($got -ne $want) {
  Log "step3: setting uniqueid"
  $n = $disk.Number
  Run-DiskPart @"
select disk $n
uniqueid disk id=$want
"@
  $disk2 = Get-Disk -Number $n
  $got2 = ("{0}" -f $disk2.Guid).Trim('{}')
  Log "after-set Guid=$got2"
} else {
  Log "step3: Guid already correct; no change"
}

# 4. Detach
Log "step4: detach"
Run-DiskPart @"
select vdisk file="$vhdx"
detach vdisk
"@

$after = (Get-Item $vhdx).Length
Log "DONE vhdx-bytes=$after"
New-Item -ItemType File -Path $done -Force | Out-Null
