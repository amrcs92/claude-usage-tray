# Builds dist\ClaudeUsageTray.exe (single portable file).
# Usage:  .\build.ps1            -> --onefile
#         .\build.ps1 -OneDir    -> folder build (fallback if antivirus flags the one-file exe)
param([switch]$OneDir)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    py -3.12 -m venv .venv
    & $py -m pip install --upgrade pip
}
& $py -m pip install -r requirements-dev.txt
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

$mode = if ($OneDir) { "--onedir" } else { "--onefile" }
& $py -m PyInstaller $mode --noconsole --clean --noconfirm `
    --name ClaudeUsageTray `
    --icon assets\icon.ico `
    --paths . `
    --add-data "app\ui;ui" `
    app\main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "Built: dist\ClaudeUsageTray$(if ($OneDir) { '\ClaudeUsageTray' }).exe"
