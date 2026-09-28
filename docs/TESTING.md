# Testing

## Quality commands

```powershell
python -m pytest -q
ruff check .
mypy src tests
```

## Current executed results

- **PASS — mocked:** 271 unit and integration tests passed.
- **PASS — environment:** MT5 executable, data directory, and demo process were found.
- **PASS — controlled dry-run:** real-terminal BUY and SELL dry-runs prepared and closed the semantic order dialog without final execution.
- **PASS — HTTP signal source:** a loopback server with a bearer token, including the refusals for a wrong token, a non-loopback URL, a redirect off loopback, an oversized body, and an unreachable endpoint.
- **PASS — named-pipe source:** a real Win32 pipe server, including authentication, a wrong token, a non-local pipe name, an oversized line, a disconnect, and two signals in one session.
- **PASS — WebSocket source:** an independently written test server, covering the handshake and accept key, authentication, masked frames, binary messages, fragmentation, continuation misuse, ping, close, size limits, and unreachable endpoints.
- **PASS — MT5 bridge source:** consumption, non-consumption of an invalid file, and ignoring the position reader's snapshots.
- **PASS — diagnostics bundle:** sections, redaction of the token, terminal-not-found and positions-unavailable as data, and a missing log directory.
- **PASS — configuration wizard:** default handling, validation refusals, refusal to change a deliberate value, preservation of unmanaged keys, and `AUTO_TRADE_ENABLE_EXECUTION=false`.
- **PASS — executable:** the Windows build runs `diagnostics`, `diagnostics-bundle`, `make-signal`, `dry-run --mock`, `configure`, and the dashboard.
- **MANUAL — pipe and WebSocket sources end to end:** each was driven once from the command line against a local writer outside the test suite, and produced a pending signal file. No MT5 is involved in either.
- **NOT RUN — installer:** `installer.iss` was never compiled; Inno Setup 6 is not installed here.
- **BLOCKED — position verification:** the MT5 Trade grid exposes no row values through UIA, Win32 `LVM_GETITEMTEXT`, or MSAA; the read-only indicator path is required.
- **NOT RUN — real order:** no real BUY/SELL click or broker order was attempted.
- **MANUAL TEST REQUIRED:** attach `AutoTradePositionReader`, open a demo position, confirm the snapshot reports it, and then test broker rejection handling.

## Test layers

- Unit: parsing, validation, risk, state machine, duplicate protection, audit, network policy, and packaging assets.
- Integration: local provider to application workflow.
- Frozen build: `diagnostics`, `diagnostics-bundle`, and a served dashboard page, which is what proves the package data was collected.
- Future UI: controlled terminal/window/control tests.
- Future E2E: only the specified MT5 demo account, with recorded date, terminal path, account type, symbol, action, volume, expected result, actual result, verification method, and status.

A click is never reported as a successful trade. Verification must be independent of the action that initiated the request.
