<#
    fmeda-toolkit - one-step launcher for Windows.

    Right-click this file and choose "Run with PowerShell", or from a
    PowerShell window in this folder:

        .\run-windows.ps1

    It creates an isolated Python environment inside this folder, installs the
    dependencies into it, runs the test suite, and opens the dashboard in your
    browser. Nothing is installed system-wide and nothing outside this folder
    is touched. Delete the folder to uninstall.

    To stop the dashboard: press Ctrl+C in the window, or just close it.
#>

$ErrorActionPreference = "Stop"

# Render the tool's output correctly on a non-UTF-8 console (cp949, cp1252...).
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "  fmeda-toolkit" -ForegroundColor Cyan
Write-Host "  ---------------------------------------------------------"

# --- 1. Find a usable Python -------------------------------------------------
$python = $null
foreach ($candidate in @("py -3.13", "py -3.12", "py -3.11", "python")) {
    $parts = $candidate.Split(" ")
    $exe = $parts[0]
    $args = if ($parts.Length -gt 1) { $parts[1..($parts.Length - 1)] } else { @() }
    try {
        $version = & $exe @args --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -match "Python 3\.(\d+)") {
            if ([int]$Matches[1] -ge 11) {
                $python = $candidate
                Write-Host "  Using $version" -ForegroundColor Green
                break
            }
        }
    } catch { }
}

if (-not $python) {
    Write-Host ""
    Write-Host "  Python 3.11 or newer was not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Install it from https://www.python.org/downloads/"
    Write-Host "  On the FIRST screen of the installer, tick" -NoNewline
    Write-Host " 'Add python.exe to PATH'" -ForegroundColor Yellow -NoNewline
    Write-Host " before"
    Write-Host "  clicking Install. That one checkbox is the usual reason this fails."
    Write-Host ""
    Write-Host "  Then close this window, open a new one, and run this script again."
    Write-Host ""
    Read-Host "  Press Enter to close"
    exit 1
}

# --- 2. Create the isolated environment --------------------------------------
if (-not (Test-Path ".venv")) {
    Write-Host "  Creating an isolated environment (.venv) ..." -ForegroundColor Gray
    $parts = $python.Split(" ")
    $exe = $parts[0]
    $args = if ($parts.Length -gt 1) { $parts[1..($parts.Length - 1)] } else { @() }
    & $exe @args -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Host "  Could not create .venv" -ForegroundColor Red; Read-Host; exit 1 }
} else {
    Write-Host "  Reusing the existing .venv" -ForegroundColor Gray
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# --- 3. Install ---------------------------------------------------------------
Write-Host "  Installing dependencies (first run takes a few minutes) ..." -ForegroundColor Gray
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e ".[dashboard,dev]"
if ($LASTEXITCODE -ne 0) { Write-Host "  Install failed." -ForegroundColor Red; Read-Host; exit 1 }

# --- 4. Prove it works before opening anything --------------------------------
Write-Host ""
Write-Host "  Running the test suite ..." -ForegroundColor Gray
& $venvPython -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Tests failed - the dashboard would not be trustworthy." -ForegroundColor Red
    Read-Host "  Press Enter to close"
    exit 1
}

Write-Host ""
Write-Host "  Metrics for the bundled fictional ECU:" -ForegroundColor Cyan
& $venvPython -m fmeda compute examples\bjb\fmeda.yaml --goal SG1

# --- 5. Launch ----------------------------------------------------------------
Write-Host ""
Write-Host "  ---------------------------------------------------------"
Write-Host "  Opening the dashboard at http://localhost:8501" -ForegroundColor Green
Write-Host "  Press Ctrl+C here to stop it."
Write-Host ""
& $venvPython -m streamlit run app.py
