# Enable and size a Windows pagefile. Run as Administrator.
$ErrorActionPreference = 'Stop'

# 1) Turn on automatic managed pagefile
$cs = Get-CimInstance -ClassName Win32_ComputerSystem
if (-not $cs.AutomaticManagedPagefile) {
    Set-CimInstance -InputObject $cs -Property @{AutomaticManagedPagefile = $true}
    Write-Output 'AutomaticManagedPagefile enabled.'
} else {
    Write-Output 'AutomaticManagedPagefile already enabled.'
}

# 2) Ensure a concrete C: pagefile of 8-32 GB as a floor
$pf = Get-CimInstance -ClassName Win32_PageFileSetting | Select-Object -First 1
if ($pf) {
    Set-CimInstance -InputObject $pf -Property @{ InitialSize = [uint32]8192; MaximumSize = [uint32]32768 }
    Write-Output ("Updated pagefile: {0} Initial={1}MB Max={2}MB" -f $pf.Name, 8192, 32768)
} else {
    New-CimInstance -ClassName Win32_PageFileSetting -Property @{
        Name        = 'C:\pagefile.sys'
        InitialSize = [uint32]8192
        MaximumSize = [uint32]32768
    } | Out-Null
    Write-Output 'Created pagefile C:\pagefile.sys Initial=8192MB Max=32768MB'
}

Write-Output 'NOTE: a reboot is required for the new pagefile size to take effect.'
