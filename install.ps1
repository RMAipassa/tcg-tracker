# Installs TCG Tracker, Playwright, and a compatible Chromium browser.
# Run from PowerShell with:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

function Test-CompatiblePython {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$PrefixArgs = @()
    )

    $arguments = @($PrefixArgs) + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)")
    & $Executable @arguments
    return $LASTEXITCODE -eq 0
}

function Find-CompatiblePython {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and (Test-CompatiblePython -Executable $py.Source -PrefixArgs @("-3"))) {
        return [pscustomobject]@{ Executable = $py.Source; PrefixArgs = @("-3") }
    }

    foreach ($name in @("python3.14", "python3.13", "python3.12", "python")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and (Test-CompatiblePython -Executable $command.Source)) {
            return [pscustomobject]@{ Executable = $command.Source; PrefixArgs = @() }
        }
    }

    $candidates = @(
        (Join-Path $env:LocalAppData "Programs\Python\Python314\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python314\python.exe"),
        (Join-Path $env:ProgramFiles "Python313\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe")
    )
    foreach ($candidate in $candidates) {
        if ((Test-Path $candidate) -and (Test-CompatiblePython -Executable $candidate)) {
            return [pscustomobject]@{ Executable = $candidate; PrefixArgs = @() }
        }
    }

    return $null
}

function Find-SystemBrowser {
    $candidates = @(
        [pscustomobject]@{ Name = "Google Chrome"; Channel = "chrome"; Path = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" },
        [pscustomobject]@{ Name = "Google Chrome"; Channel = "chrome"; Path = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" },
        [pscustomobject]@{ Name = "Google Chrome"; Channel = "chrome"; Path = "$env:LocalAppData\Google\Chrome\Application\chrome.exe" },
        [pscustomobject]@{ Name = "Microsoft Edge"; Channel = "msedge"; Path = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe" },
        [pscustomobject]@{ Name = "Microsoft Edge"; Channel = "msedge"; Path = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe" },
        [pscustomobject]@{ Name = "Microsoft Edge"; Channel = "msedge"; Path = "$env:LocalAppData\Microsoft\Edge\Application\msedge.exe" }
    )
    return $candidates | Where-Object { Test-Path $_.Path } | Select-Object -First 1
}

if (-not (Test-Path $VenvPython)) {
    $bootstrapPython = Find-CompatiblePython
    if (-not $bootstrapPython) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "Python 3.12+ was not found and winget is unavailable. Install Python from https://www.python.org/downloads/."
        }

        Write-Host "Python 3.12+ was not found. Installing Python 3.12 with winget..."
        & $winget.Source install --exact --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Failed to install Python 3.12 with winget." }

        $bootstrapPython = Find-CompatiblePython
        if (-not $bootstrapPython) {
            throw "Python 3.12 was installed but could not be located. Open a new PowerShell window and rerun install.ps1."
        }
    }

    Write-Host "Creating Python virtual environment..."
    $venvArguments = @($bootstrapPython.PrefixArgs) + @("-m", "venv", $Venv)
    & $bootstrapPython.Executable @venvArguments
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the Python virtual environment." }
}

& $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) { throw "TCG Tracker requires Python 3.12 or newer. Delete .venv and rerun this script after upgrading Python." }

Write-Host "Installing Python dependencies..."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip." }
& $VenvPython -m pip install -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Failed to install Python dependencies." }

$systemBrowser = Find-SystemBrowser
if (-not $systemBrowser) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Chrome or Edge was not found and winget is unavailable. Install Google Chrome, then rerun this script."
    }

    Write-Host "Chrome or Edge was not found. Installing Google Chrome with winget..."
    & $winget.Source install --exact --id Google.Chrome --scope machine --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Failed to install Google Chrome with winget." }
    $systemBrowser = Find-SystemBrowser
    if (-not $systemBrowser) { throw "Google Chrome was installed but could not be located." }
}

Write-Host "Checking Playwright with $($systemBrowser.Name)..."
& $VenvPython -c "import sys; from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(channel=sys.argv[1], headless=True); b.close(); p.stop()" $systemBrowser.Channel
if ($LASTEXITCODE -ne 0) { throw "Playwright could not launch $($systemBrowser.Name)." }

Write-Host "TCG Tracker dependencies installed successfully." -ForegroundColor Green
