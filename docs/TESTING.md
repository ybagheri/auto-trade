# Testing

## Quality commands

```powershell
python -m pytest -q
ruff check .
mypy src tests
```

## Current executed results

- **PASS — mocked:** 271 unit and integration tests passed.
- **PASS — environment:** Alpari MT5 build 6184, its data directory, and the running `Alpari-MT5-Demo` process were found; `diagnostics` reports `found`.
- **PASS — indicator build:** `MetaEditor64 /compile` reported 0 errors and 0 warnings for `AutoTradePositionReader`, which is registered in the Navigator and attached to the `EURUSD,M5` chart.
- **PASS — position snapshot:** `position-snapshot` reports `AVAILABLE` from a live snapshot whose sequence advances and whose `complete` flag is true.
- **PASS — staleness guard:** `position-snapshot` refused a real snapshot from an earlier session as `stale (84756.8s old, limit 30s)` instead of reporting an empty account.
- **PASS — controlled dry-run:** on Alpari MT5 6184, real-terminal BUY and SELL dry-runs reached `ORDER_READY`, closed the order dialog, used no final control, and left the account with no position; `recovery` reported no pending or unknown record.
- **PASS — HTTP signal source:** a loopback server with a bearer token, including the refusals for a wrong token, a non-loopback URL, a redirect off loopback, an oversized body, and an unreachable endpoint.
- **PASS — named-pipe source:** a real Win32 pipe server, including authentication, a wrong token, a non-local pipe name, an oversized line, a disconnect, and two signals in one session.
- **PASS — WebSocket source:** an independently written test server, covering the handshake and accept key, authentication, masked frames, binary messages, fragmentation, continuation misuse, ping, close, size limits, and unreachable endpoints.
- **PASS — MT5 bridge source:** consumption, non-consumption of an invalid file, and ignoring the position reader's snapshots.
- **PASS — diagnostics bundle:** sections, redaction of the token, terminal-not-found and positions-unavailable as data, and a missing log directory.
- **PASS — configuration wizard:** default handling, validation refusals, refusal to change a deliberate value, preservation of unmanaged keys, and `AUTO_TRADE_ENABLE_EXECUTION=false`.
- **PASS — executable:** the Windows build runs `diagnostics`, `diagnostics-bundle`, `make-signal`, `dry-run --mock`, `configure`, and the dashboard.
- **MANUAL — pipe and WebSocket sources end to end:** each was driven once from the command line against a local writer outside the test suite, and produced a pending signal file. No MT5 is involved in either.
- **NOT RUN — installer:** `installer.iss` was never compiled; Inno Setup 6 is not installed here.
- **BLOCKED — position verification:** the MT5 Trade grid exposes no row values through UIA, Win32 `LVM_GETITEMTEXT`, or MSAA, and the chart context menu is not in the accessibility tree, so opening a chart and attaching the indicator are human actions. The snapshot read itself is confirmed; what is missing is a real position to accept.
- **NOT RUN — real order:** no real BUY/SELL click or broker order was attempted.
- **MANUAL TEST REQUIRED:** open one demo position by hand, confirm the snapshot reports it, then close it. [demo validation](MT5_DEMO_VALIDATION.md) holds the procedure and the record.

## Test layers

- Unit: parsing, validation, risk, state machine, duplicate protection, audit, network policy, and packaging assets.
- Integration: local provider to application workflow.
- Frozen build: `diagnostics`, `diagnostics-bundle`, and a served dashboard page, which is what proves the package data was collected.
- Future UI: controlled terminal/window/control tests.
- Future E2E: only the specified MT5 demo account, with recorded date, terminal path, account type, symbol, action, volume, expected result, actual result, verification method, and status.

A click is never reported as a successful trade. Verification must be independent of the action that initiated the request.
