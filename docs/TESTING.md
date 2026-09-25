# Testing

## Quality commands

```powershell
python -m pytest -q
ruff check .
mypy src tests
```

## Current executed results

- **PASS — mocked:** 27 unit and integration tests passed.
- **PASS — environment:** MT5 executable, data directory, configured process, responsive demo window, and active `XAUUSD` chart were found.
- **PASS — controlled dry-run:** real-terminal BUY and SELL dry-runs opened the UIA order dialog, set Symbol/Volume/optional fields, and closed it without final execution; mock dry-run also passed.
- **PASS — recovery logic:** durable ledger tests cover completed, requested, and unknown execution records.
- **BLOCKED — live position snapshot:** MT5 Trade table `10328` is detected, but its row text is inaccessible through UIA on this build; the provider fails closed.
- **NOT RUN — real order:** no real BUY/SELL click or broker order was attempted.
- **MANUAL TEST REQUIRED:** actual symbol switching, DPI behavior, broker rejection handling, and an independent position observation method.

## Test layers

- Unit: parsing, validation, risk, state machine, duplicate protection, and audit behavior.
- Integration: local provider to application workflow.
- Future UI: controlled terminal/window/control tests.
- Future E2E: only the specified MT5 demo account, with recorded date, terminal path, account type, symbol, action, volume, expected result, actual result, verification method, and status.

A click is never reported as a successful trade. Verification must be independent of the action that initiated the request.
