param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
& $Python -m auto_trade diagnostics
