param(
    [string]$DataPath = "",
    [string]$MetaEditor = "C:\Program Files\Alpari MT5_2\MetaEditor64.exe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "mql5\Indicators\AutoTradePositionReader.mq5"

if (-not $DataPath) {
    if ($env:AUTO_TRADE_DATA_PATH) {
        $DataPath = $env:AUTO_TRADE_DATA_PATH
    } else {
        throw "Pass -DataPath or set AUTO_TRADE_DATA_PATH to the MT5 data directory."
    }
}

if (-not (Test-Path -LiteralPath $MetaEditor)) {
    throw "MetaEditor64.exe was not found at $MetaEditor"
}

$targetDir = Join-Path $DataPath "MQL5\Indicators"
if (-not (Test-Path -LiteralPath $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

$target = Join-Path $targetDir "AutoTradePositionReader.mq5"
Copy-Item -LiteralPath $source -Destination $target -Force
Write-Host "Installed $target"

$log = Join-Path $env:TEMP "auto_trade_metaeditor_reader.log"
$process = Start-Process -FilePath $MetaEditor `
    -ArgumentList "/compile:$target", "/log:$log" `
    -Wait -PassThru -WindowStyle Hidden

$compiled = Join-Path $targetDir "AutoTradePositionReader.ex5"
if (Test-Path -LiteralPath $log) {
    Get-Content $log | ForEach-Object { Write-Host "  $_" }
}

if (-not (Test-Path -LiteralPath $compiled)) {
    throw "Compilation did not produce $compiled"
}

Write-Host "Compiled $compiled"
Write-Host "Attach it once: Indicators -> AutoTradePositionReader, then confirm OK."
Write-Host "The program reads positions and writes a snapshot; it contains no trade calls."
