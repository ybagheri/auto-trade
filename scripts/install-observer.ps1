param(
    [string]$DataPath = "",
    [string]$MetaEditor = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "mql5\Experts\AutoTradePositionObserver.mq5"

if (-not $DataPath) {
    if ($env:AUTO_TRADE_DATA_PATH) {
        $DataPath = $env:AUTO_TRADE_DATA_PATH
    } else {
        throw "Pass -DataPath or set AUTO_TRADE_DATA_PATH to the MT5 data directory."
    }
}

if (-not $MetaEditor) {
    $exe = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    $terminal = Join-Path (Split-Path -Parent (Split-Path -Parent $exe)) "terminal64.exe"
    $MetaEditor = Join-Path (Split-Path -Parent $terminal) "metaeditor64.exe"
}

if (-not (Test-Path -LiteralPath $MetaEditor)) {
    throw "MetaEditor64.exe was not found at $MetaEditor"
}

$targetDir = Join-Path $DataPath "MQL5\Experts"
if (-not (Test-Path -LiteralPath $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

# The observer is an Expert Advisor attached to a chart, not an MQL5 Service.
# Remove any earlier copy from the Services folder so MT5 does not see two
# programs with the same name and prompt about replacing one with the other.
$staleDir = Join-Path $DataPath "MQL5\Services"
foreach ($name in @("AutoTradePositionObserver.mq5", "AutoTradePositionObserver.ex5")) {
    $stale = Join-Path $staleDir $name
    if (Test-Path -LiteralPath $stale) {
        Remove-Item -LiteralPath $stale -Force
        Write-Host "Removed stale copy $stale"
    }
}
$staleIni = Join-Path $DataPath "config\services.ini"
if (Test-Path -LiteralPath $staleIni) {
    Remove-Item -LiteralPath $staleIni -Force
    Write-Host "Removed $staleIni"
}

$target = Join-Path $targetDir "AutoTradePositionObserver.mq5"
Copy-Item -LiteralPath $source -Destination $target -Force
Write-Host "Installed $target"

$log = Join-Path $env:TEMP "auto_trade_metaeditor.log"
$process = Start-Process -FilePath $MetaEditor `
    -ArgumentList "/compile:$target", "/log:$log" `
    -Wait -PassThru -WindowStyle Hidden

$compiled = Join-Path $targetDir "AutoTradePositionObserver.ex5"
if (Test-Path -LiteralPath $log) {
    Get-Content $log | ForEach-Object { Write-Host "  $_" }
}

if (-not (Test-Path -LiteralPath $compiled)) {
    throw "Compilation did not produce $compiled"
}

Write-Host "Compiled $compiled"
Write-Host ""
Write-Host "Attach it once in the MT5 terminal:"
Write-Host "  Navigator -> Expert Advisors -> AutoTradePositionObserver"
Write-Host "  -> drag it onto a chart, or right click -> Attach to Chart, then OK"
Write-Host ""
Write-Host "If the chart already shows the name, it is attached and there is nothing to do."
Write-Host "MT5 restores the attachment when the terminal reopens."
Write-Host ""
Write-Host "Do not use the MQL5 Services folder or 'Add Service': with this terminal build"
Write-Host "that path does not initialise the program."
Write-Host "Snapshots appear in $(Join-Path (Split-Path -Parent $targetDir) 'Files')"
