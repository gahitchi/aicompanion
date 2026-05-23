# Jade one-command installer — Windows (PowerShell 5.1+).
#
#   From a clone:  powershell -ExecutionPolicy Bypass -File install.ps1
#   One-liner:     irm https://raw.githubusercontent.com/gahitchi/aicompanion/main/install.ps1 | iex
#
# Thin bootstrap: locate the repo + python, hand off to installer/setup.py
# (which installs uv, deps, Ollama, the model, autostart, and smoke-tests).
$ErrorActionPreference = "Stop"

$scriptDir = $PSScriptRoot
if ($scriptDir -and (Test-Path (Join-Path $scriptDir "installer\setup.py"))) {
    $repo = $scriptDir
} else {
    $repo = if ($env:JADE_HOME) { $env:JADE_HOME } else { Join-Path $env:USERPROFILE ".jade-companion" }
    if (-not (Test-Path (Join-Path $repo ".git"))) {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Write-Error "git is required to fetch Jade (winget install Git.Git)."; exit 1
        }
        Write-Host "Cloning Jade into $repo ..."
        git clone --depth 1 https://github.com/gahitchi/aicompanion $repo
    }
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    Write-Error "Python 3 is required to bootstrap (winget install Python.Python.3.12), then re-run."
    exit 1
}

& $py.Source (Join-Path $repo "installer\setup.py") @args
exit $LASTEXITCODE
