param(
    [string]$Python = "python",
    [switch]$SkipTests
)

# Builds the Windows executable into dist\auto-trade\auto-trade.exe.
#
# The build runs in a throwaway virtual environment under .build so it never
# depends on, and never disturbs, the interpreter used for development. PyInstaller
# is a build requirement only; it is not a runtime dependency of the application.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $root ".build"
$venv = Join-Path $buildRoot "venv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not $SkipTests) {
    & (Join-Path $PSScriptRoot "test.ps1") -Python $Python
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Creating the build environment in $venv"
    & $Python -m venv $venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "Installing build requirements"
& $python -m pip install --disable-pip-version-check --quiet --upgrade pip
& $python -m pip install --disable-pip-version-check --quiet -e "$root[dev,windows]" "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Building the executable"
& $python -m PyInstaller --noconfirm --clean (Join-Path $root "packaging\auto-trade.spec")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Join-Path $root "dist\auto-trade\auto-trade.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "The build did not produce $exe"
}

# The MT5 side of the project ships next to the executable so an operator can
# install and compile the read-only indicator without a source checkout.
Write-Host "Copying the operator-facing files"
$payload = Join-Path $root "dist\auto-trade"
Copy-Item -LiteralPath (Join-Path $root "README.md") -Destination $payload -Force
Copy-Item -LiteralPath (Join-Path $root "LICENSE") -Destination $payload -Force
Copy-Item -LiteralPath (Join-Path $root "docs") -Destination $payload -Recurse -Force
Copy-Item -LiteralPath (Join-Path $root "mql5") -Destination $payload -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $payload "scripts") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root "scripts\install-position-reader.ps1") `
    -Destination (Join-Path $payload "scripts") -Force

# A build that cannot serve the dashboard or install the indicator is broken in a
# way the executable itself will not report at start-up, so it fails here.
$required = @(
    "auto-trade.exe",
    "scripts\install-position-reader.ps1",
    "mql5\Indicators\AutoTradePositionReader.mq5",
    "docs\POSITION_READER.md"
)
foreach ($item in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $payload $item))) {
        throw "The build is incomplete: $item is missing from $payload"
    }
}

Write-Host "Built $exe"
Write-Host "Smoke test the result before trusting it:"
Write-Host "  $exe diagnostics"
Write-Host "  $exe diagnostics-bundle"
Write-Host "An executable that cannot pass those two commands is not a working build."
