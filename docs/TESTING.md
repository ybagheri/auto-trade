# Testing

## Quality commands

```powershell
python -m pytest -q
ruff check .
mypy src tests
```

## Current executed results

- **PASS — mocked:** 412 unit and integration tests passed.
- **PASS — bilingual documentation:** every page describing a refusal, a recovery, or an observation has a Persian translation, each linking to the other, and both READMEs index both languages. `tests/unit/test_documentation.py` fails when a page is unaccounted for, a cross-link is missing, a safety section is dropped, a control identifier is mistyped, or a gate appears on one side of the execution tables only. It found three pages with no way back to their translation and one page accounted for by neither list.
- **PASS — metrics and latency:** phase latency and counters are derived from the audit log rather than collected in memory, so a run that crashed between the click and the observation is still measured. Covered: each phase measured between its two recorded states, an unmeasured phase reporting `null` rather than zero, results counted by settled state, an unresolved attempt identified, a truncated log saying so, an unparseable line counted rather than dropped, and a backwards clock reported instead of producing a negative duration. Verified end to end through a real `AuditLogger`, a real `ExecutionWorkflow`, and the shipped `metrics` command.
- **PASS — crash between the click and the observation:** a process that dies after the final control is used leaves the durable record `REQUESTED` with no result and no `order_reference`; a restarted process refuses the same signal as a duplicate without opening the order dialog; the refused retry cannot overwrite the pending record; `recovery` lists it for review and only `reconcile` settles it; and a fill that was observed but whose result never reached disk is still not recorded as `ACCEPTED`. A snapshot written before a terminal restart is refused as stale rather than read as the current account.
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
- **PASS — guarded demo order:** on Alpari MT5 6184, `execute --confirm-demo` for EURUSD BUY 0.01 returned `ACCEPTED` with `order_reference 382631622`, an empty baseline, and the observed position in the evidence. The first attempt returned `UNKNOWN` and produced three defects, each now covered by a regression test: a destroyed dialog read as live, one unreadable snapshot ending verification, and an unknown state that hid its cause.
- **NOT RUN — real account:** no live or funded account was used at any point; every order above was on the demo account the title identifies.
- **NOT RUN — installer:** `installer.iss` was never compiled; Inno Setup 6 is not installed here.
- **BLOCKED — position verification by hand:** the MT5 Trade grid exposes no row values through UIA, Win32 `LVM_GETITEMTEXT`, or MSAA, and the chart context menu is not in the accessibility tree, so opening a chart and placing a position by hand are human actions. The equivalent observation path was proven by the guarded order instead.
- **NOT RUN — closing a position:** superseded. `close-position` returned `CLOSED` on the demo account with the ticket gone from the snapshot, after two defects were found and fixed: a popup menu read before its entries existed, and a click at a screen coordinate that needed the terminal focused first.
- **MANUAL TEST REQUIRED:** open one demo position by hand, confirm the snapshot reports it, then close it. [demo validation](MT5_DEMO_VALIDATION.md) holds the procedure and the record.

## Test layers

- Unit: parsing, validation, risk, state machine, duplicate protection, audit, network policy, and packaging assets.
- Integration: local provider to application workflow, and a crash between the click and the observation.
- Frozen build: `diagnostics`, `diagnostics-bundle`, and a served dashboard page, which is what proves the package data was collected.
- Future UI: controlled terminal/window/control tests.
- Future E2E: only the specified MT5 demo account, with recorded date, terminal path, account type, symbol, action, volume, expected result, actual result, verification method, and status.

A click is never reported as a successful trade. Verification must be independent of the action that initiated the request.
