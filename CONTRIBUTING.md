# Contributing

1. Inspect `git status` and recent history before changing a major area.
2. Keep domain logic independent from Windows UI automation.
3. Add or update tests for parsing, risk, state transitions, and safety behavior.
4. Run `python -m pytest -q`, `ruff check .`, and `mypy src tests`.
5. Do not add credentials, real-account tests, or hard-coded user coordinates.
6. Record MT5 demo validation with the date, terminal, account type, symbol, action, volume, expected result, actual result, verification method, and status.
7. Do not enable a final execution control until verification and fail-closed recovery are implemented.
