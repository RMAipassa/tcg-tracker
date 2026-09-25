# TCG Tracker installer for Windows.
# Run in an *Administrator* PowerShell from the tcg-tracker folder:
#   powershell -ExecutionPolicy Bypass -File deploy\install.ps1 -Domain tcg.yourdomain.nl
# When AMP runs the tracker, only set up HTTPS (Caddy) with:
#   powershell -ExecutionPolicy Bypass -File deploy\install.ps1 -Domain tcg.yourdomain.nl -CaddyOnly -Port 8080
param(
    [Parameter(Mandatory = $true)][string]$Domain,
    [switch]$SkipCaddy,
    [switch]$CaddyOnly,
    [int]$Port = 8080
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an Administrator PowerShell."
}

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$trigger = New-ScheduledTaskTrigger -AtStartup

if (-not $CaddyOnly) {
    # 1. Python virtualenv + dependencies
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) { throw "Python not found. Install Python 3.12+ from https://www.python.org/downloads/ (tick 'Add python.exe to PATH')." }
    if (-not (Test-Path ".venv")) { & py -3 -m venv .venv }
    & .venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
    & .venv\Scripts\python.exe -m pip install -r requirements.txt

    # 2. Config
    if (-not (Test-Path "config.toml")) {
        $secret = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
        $config = (Get-Content config.example.toml -Raw).Replace("replace-with-a-long-random-string", $secret).Replace("https://tcg.example.nl", "https://$Domain")
        [IO.File]::WriteAllText("$Root\config.toml", $config)  # UTF-8 without BOM
        Write-Host "Created config.toml - edit it now (password, Discord webhook, email)." -ForegroundColor Yellow
    }

    # 3. Scheduled task: tracker starts at boot, restarts when it crashes
    $tracker = New-ScheduledTaskAction -Execute "$Root\deploy\start-tracker.cmd" -WorkingDirectory $Root
    Register-ScheduledTask -TaskName "TCG Tracker" -Action $tracker -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "Registered scheduled task 'TCG Tracker'."
}

# 4. Caddy (automatic HTTPS) in front of the app
if (-not $SkipCaddy) {
    $caddyDir = "$Root\deploy\caddy"
    New-Item -ItemType Directory -Force $caddyDir | Out-Null
    if (-not (Test-Path "$caddyDir\caddy.exe")) {
        Write-Host "Downloading Caddy..."
        Invoke-WebRequest "https://caddyserver.com/api/download?os=windows&arch=amd64" -OutFile "$caddyDir\caddy.exe"
    }
    [IO.File]::WriteAllText("$caddyDir\Caddyfile", (Get-Content "$Root\deploy\Caddyfile.template" -Raw).Replace("YOUR_DOMAIN", $Domain).Replace("8080", "$Port"))

    $caddy = New-ScheduledTaskAction -Execute "$caddyDir\caddy.exe" -Argument "run --config `"$caddyDir\Caddyfile`"" -WorkingDirectory $caddyDir
    Register-ScheduledTask -TaskName "TCG Tracker HTTPS (Caddy)" -Action $caddy -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "Registered scheduled task 'TCG Tracker HTTPS (Caddy)'."

    foreach ($port in 80, 443) {
        if (-not (Get-NetFirewallRule -DisplayName "TCG Tracker $port" -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName "TCG Tracker $port" -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow | Out-Null
        }
    }
    Write-Host "Opened Windows Firewall ports 80 and 443."
}

Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Green
Write-Host " 1. Edit config.toml (password, Discord webhook, email)$(if ($CaddyOnly) { ' in the AMP instance folder' })."
Write-Host " 2. DNS: point $Domain (A record) to your public IP."
Write-Host " 3. Router: forward TCP 80 and 443 to this PC."
if ($CaddyOnly) {
    Write-Host " 4. Start now:  Start-ScheduledTask 'TCG Tracker HTTPS (Caddy)'  (and start the tracker in AMP)"
} else {
    Write-Host " 4. Start now:  Start-ScheduledTask 'TCG Tracker'; Start-ScheduledTask 'TCG Tracker HTTPS (Caddy)'"
}
Write-Host " 5. Open https://$Domain on your phone and add it to your home screen."
