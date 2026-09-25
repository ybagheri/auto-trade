# Testing

## Quality commands

```powershell
python -m pytest -q
ruff check .
mypy src tests
```

## Current executed results

- **PASS — mocked:** 15 unit and integration tests passed.
- **PASS — environment:** MT5 executable, data directory, configured process, responsive demo window, and active `XAUUSD` chart were found.
- **PASS — controlled dry-run:** real-terminal BUY and SELL dry-runs completed without final execution controls; mock dry-run also passed.
- **NOT RUN — real order:** no real BUY/SELL click or broker order was attempted.
- **MANUAL TEST REQUIRED:** order dialog controls, actual symbol switching, DPI behavior, and independent position verification.

## Test layers

- Unit: parsing, validation, risk, state machine, duplicate protection, and audit behavior.
- Integration: local provider to application workflow.
- Future UI: controlled terminal/window/control tests.
- Future E2E: only the specified MT5 demo account, with recorded date, terminal path, account type, symbol, action, volume, expected result, actual result, verification method, and status.

A click is never reported as a successful trade. Verification must be independent of the action that initiated the request.
