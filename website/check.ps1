[CmdletBinding()]
param([string]$Python = ".venv\Scripts\python.exe")
Set-Location (Split-Path -Parent $PSScriptRoot)
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$pytestTemp = Join-Path (Get-Location) ("tmp/website-check-" + [guid]::NewGuid().ToString("N"))
function Invoke-Check([string]$Name, [scriptblock]$Command) {
  & $Command
  if ($LASTEXITCODE -ne 0) { throw "$Name failed." }
}
Invoke-Check "Python compilation" { & $pythonPath -m compileall -q server.py backend website }
Invoke-Check "Python suites" { & $pythonPath -m pytest tests website/tests -q -o cache_dir=tmp/pytest-website-cache --basetemp=$pytestTemp }
Invoke-Check "Desktop schema" { & npm.cmd run schema:check:desktop }
Invoke-Check "Shared lint" { & npm.cmd run lint }
Invoke-Check "Website lint" { & npm.cmd exec -- eslint --config website/eslint.config.mjs website }
Invoke-Check "Shared unit tests" { & npm.cmd test }
Invoke-Check "Shared frontend" { & npm.cmd run build }
Invoke-Check "Shared standalone" { & $pythonPath scripts/build-standalone.py }
$previousTestPython = $env:FISH_TEST_PYTHON
$previousAppPort = $env:PORT
try {
  $env:FISH_TEST_PYTHON = $pythonPath
  # Exercise the app port inherited in CI; Playwright must override it per suite.
  $env:PORT = "8080"
  Invoke-Check "Shared browser tests" { & npm.cmd run test:e2e }
  Invoke-Check "Website frontend" { & node website/build.mjs }
  Invoke-Check "Website runtime tests" { & node --test website/tests/*.test.mjs }
  Invoke-Check "Website browser tests" { & npm.cmd exec -- playwright test --config website/playwright.config.cjs }
} finally {
  $env:FISH_TEST_PYTHON = $previousTestPython
  $env:PORT = $previousAppPort
}
Write-Output "Shared and website checks passed. Website assets are built."
