param(
    [string]$DataPath = "",
    [string]$MetaEditor = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "mql5\Services\AutoTradePositionObserver.mq5"

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

$targetDir = Join-Path $DataPath "MQL5\Services"
if (-not (Test-Path -LiteralPath $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
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
Write-Host "Start it once in the MT5 terminal:"
Write-Host "  Navigator -> Services -> AutoTradePositionObserver -> right click -> Attach to Chart"
Write-Host "  then confirm with OK. Leave that chart open, and re-attach after a terminal restart."
Write-Host ""
Write-Host "Do not use 'Add Service': with this terminal build that path compiles a script"
Write-Host "which the terminal starts and immediately stops without running OnInit."
Write-Host "Snapshots appear in $(Join-Path (Split-Path -Parent $targetDir) 'Files')"
