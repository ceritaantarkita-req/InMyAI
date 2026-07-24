#Requires -Version 5.1
# InMyAI one-command installer for Windows.
#
# Intended usage once this repo is pushed to a public GitHub repo:
#
#   irm https://raw.githubusercontent.com/ceritaantarkita-req/InMyAI/main/install.ps1 | iex
#
# `irm` (Invoke-RestMethod) downloads this file's text, `iex`
# (Invoke-Expression) runs it in the current PowerShell session - the same
# pattern used by most "curl | bash"-style installers, adapted for
# PowerShell. Nothing here is saved to disk or executed as a standalone
# .ps1 file, which is why it works even under a restrictive
# ExecutionPolicy that would otherwise block running scripts directly.
#
# The whole thing is wrapped in a function and uses `return`/`throw`
# instead of `exit` on purpose: `exit` inside a script run via `iex` closes
# the *entire* PowerShell window it's running in, not just this script -
# that's a common gotcha with this installer pattern. `return`/`throw`
# only unwind this function.

function Install-InMyAI {
    $ErrorActionPreference = 'Stop'

    $RepoUrl = 'https://github.com/ceritaantarkita-req/InMyAI.git'
    $InstallDir = Join-Path $HOME 'InMyAI'

    function Test-CommandExists([string]$Name) {
        return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
    }

    Write-Host ''
    Write-Host 'InMyAI installer' -ForegroundColor Green
    Write-Host 'Local-first AI workspace - this clones the repo and installs everything needed to run it.'
    Write-Host ''

    Write-Host '==> Checking prerequisites' -ForegroundColor Cyan
    $missing = @()
    if (-not (Test-CommandExists git)) { $missing += 'Git (https://git-scm.com/download/win)' }
    if (-not (Test-CommandExists node)) { $missing += 'Node.js 22+ (https://nodejs.org)' }
    if (-not (Test-CommandExists python) -and -not (Test-CommandExists py)) {
        $missing += 'Python 3.11-3.13 (https://www.python.org/downloads/ - check "Add python.exe to PATH" during install)'
    }
    if ($missing.Count -gt 0) {
        Write-Host 'Missing prerequisites:' -ForegroundColor Red
        $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
        Write-Host "`nInstall the above, open a new PowerShell window, and run this command again." -ForegroundColor Yellow
        return
    }
    Write-Host 'git, node, and python are all available.' -ForegroundColor Green

    try {
        if (Test-Path $InstallDir) {
            Write-Host "`n==> Existing install found at $InstallDir - updating it" -ForegroundColor Cyan
            Push-Location $InstallDir
            git pull --ff-only
        }
        else {
            Write-Host "`n==> Cloning InMyAI into $InstallDir" -ForegroundColor Cyan
            git clone $RepoUrl $InstallDir
            Push-Location $InstallDir
        }

        Write-Host "`n==> Installing dependencies (first run can take a few minutes)" -ForegroundColor Cyan
        npm run setup
        if ($LASTEXITCODE -ne 0) { throw 'npm run setup failed - see the error above.' }

        Write-Host "`n==> Starting InMyAI" -ForegroundColor Cyan
        Write-Host 'Once ready: Web -> http://127.0.0.1:3000  API docs -> http://127.0.0.1:8000/docs' -ForegroundColor Green
        Write-Host 'Press Ctrl+C to stop the servers.' -ForegroundColor Green
        npm run dev
    }
    finally {
        Pop-Location -ErrorAction SilentlyContinue
    }
}

Install-InMyAI
