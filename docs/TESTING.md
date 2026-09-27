# Testing

## Quality commands

```powershell
python -m pytest -q
ruff check .
mypy src tests
```

## Current executed results

- **PASS — mocked:** 136 unit and integration tests passed.
- **PASS — environment:** MT5 executable, data directory, and demo process were found.
- **PASS — controlled dry-run:** real-terminal BUY and SELL dry-runs prepared and closed the semantic order dialog without final execution.
- **BLOCKED — position verification:** the MT5 Trade grid exposes no row values through UIA, Win32 `LVM_GETITEMTEXT`, or MSAA; the UI reader fails closed.
- **NOT RUN — real order:** no real BUY/SELL click or broker order was attempted.
- **MANUAL TEST REQUIRED:** actual symbol switching, DPI behavior, broker rejection handling, and an approved non-OrderSend position observation method.

## Test layers

- Unit: parsing, validation, risk, state machine, duplicate protection, and audit behavior.
- Integration: local provider to application workflow.
- Future UI: controlled terminal/window/control tests.
- Future E2E: only the specified MT5 demo account, with recorded date, terminal path, account type, symbol, action, volume, expected result, actual result, verification method, and status.

A click is never reported as a successful trade. Verification must be independent of the action that initiated the request.
