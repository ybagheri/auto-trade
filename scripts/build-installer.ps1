param(
    [string]$Iscc = "",
    [string]$Python = "python"
)

# Compiles the Inno Setup installer from dist\auto-trade into dist\installer.
#
# Run scripts\build-exe.ps1 first; this script refuses to package a build that
# does not exist rather than producing an installer with an empty program folder.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$build = Join-Path $root "dist\auto-trade"
$exe = Join-Path $build "auto-trade.exe"

if (-not (Test-Path -LiteralPath $exe)) {
    throw "No build found at $exe. Run scripts\build-exe.ps1 first."
}

if (-not $Iscc) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { $Iscc = $candidate; break }
    }
}

if (-not $Iscc) {
    throw "Inno Setup 6 was not found. Install it, or pass -Iscc <path to ISCC.exe>."
}

Write-Host "Compiling the installer with $Iscc"
& $Iscc (Join-Path $root "packaging\installer.iss")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$setup = Get-ChildItem -Path (Join-Path $root "dist\installer") -Filter "*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $setup) {
    throw "The installer script did not produce an executable in dist\installer"
}
Write-Host "Built $($setup.FullName)"
