[CmdletBinding()]
param([string]$Python = ".venv\Scripts\python.exe")
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$version = (& $pythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($version -ne "3.13") { throw "The website requires a Python 3.13 environment. See website/README.md." }
& node website/build.mjs
if ($LASTEXITCODE -ne 0) { throw "Website frontend build failed." }
& $pythonPath -m website.server
