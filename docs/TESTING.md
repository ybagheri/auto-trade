# Testing

## Quality commands

```powershell
python -m pytest -q
ruff check .
mypy src tests
```

## Current executed results

- **PASS — mocked:** 15 unit and integration tests passed.
- **PASS — environment:** MT5 executable, data directory, and configured process were found by diagnostics.
- **NOT RUN — real order:** no real BUY/SELL click or broker order was attempted.
- **MANUAL TEST REQUIRED:** UI tree, DPI, symbol selection, order dialog, and position verification.

## Test layers

- Unit: parsing, validation, risk, state machine, duplicate protection, and audit behavior.
- Integration: local provider to application workflow.
- Future UI: controlled terminal/window/control tests.
- Future E2E: only the specified MT5 demo account, with recorded date, terminal path, account type, symbol, action, volume, expected result, actual result, verification method, and status.

A click is never reported as a successful trade. Verification must be independent of the action that initiated the request.
