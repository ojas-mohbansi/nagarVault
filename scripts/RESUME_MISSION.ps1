# Continuation after reboot. Run: powershell -ExecutionPolicy Bypass -File RESUME_MISSION.ps1
$ErrorActionPreference = 'Continue'
$repo = 'C:\Users\styli\OneDrive\Documents\GitHub\nagarVault'
$installer = Join-Path $env:TEMP 'DockerDesktopInstaller_492.exe'
$url = 'https://desktop.docker.com/win/main/amd64/240144/Docker Desktop Installer.exe'
$dockerCli = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'

Write-Output '=== 1. Waiting for network ==='
$ok = $false
for ($i = 0; $i -lt 24; $i++) {
    if (Test-NetConnection -ComputerName 'desktop.docker.com' -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue) { $ok = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $ok) { Write-Output 'FATAL: no network'; exit 1 }
Write-Output 'network ok'

Write-Output '=== 2. Verifying pagefile ==='
Get-CimInstance Win32_PageFileUsage | Format-List Name, AllocatedBaseSize

if (-not (Test-Path $dockerCli)) {
    Write-Output '=== 3. Downloading Docker Desktop 4.92 (full installer, ~600 MB) ==='
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    Write-Output '=== 4. Installing silently (may take several minutes) ==='
    $proc = Start-Process -FilePath $installer -ArgumentList 'install', '--quiet', '--accept-license', '--backend=wsl-2', '--no-windows-containers' -Wait -PassThru
    Write-Output ("installer exit code: " + $proc.ExitCode)
    if ($proc.ExitCode -ne 0) { Write-Output 'FATAL: installer failed'; exit 1 }
} else {
    Write-Output '=== 3-4. Docker Desktop already installed, skipping download/install ==='
}

Write-Output '=== 5. Starting Docker Desktop ==='
Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'

Write-Output '=== 6. Waiting for engine ==='
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 10
    & $dockerCli info 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
}
if ($ready) {
    Write-Output 'ENGINE READY'
    & $dockerCli images --format '{{.Repository}}:{{.Tag}}'
} else {
    Write-Output 'FATAL: engine did not come up in 10 minutes'
    exit 1
}
