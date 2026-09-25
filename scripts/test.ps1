param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
& $Python -m pytest -q
& ruff check .
& mypy src tests
