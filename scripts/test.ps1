param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# numpy ships type stubs that require Python 3.12+ syntax. It reaches mypy only
# through unrelated tooling installed in this interpreter, never through this
# project, so .typestubs shadows it with a permissive stub. That keeps the
# documented `mypy src tests` command working at the declared python_version.
if (Test-Path -LiteralPath "$root\.typestubs") {
    $env:MYPYPATH = "$root\.typestubs"
}

& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Python -m mypy src tests
exit $LASTEXITCODE
