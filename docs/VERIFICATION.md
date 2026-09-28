# Verification

Verification is independent of the UI action that initiated an order. A button click is recorded as an action only.

## Current implementation

`PositionChangeVerifier` compares before/after `PositionSnapshot` tuples. It accepts only exactly one new position matching the requested symbol, side, and volume. No match or multiple matches are treated as unverified. The logic is covered by mocked tests.

`MT5PositionSnapshotProvider` reads the Trade table identified by Automation ID `10328`. On the current terminal build, the table exposes headers and a row count but not row text values through UI Automation, Win32 `LVM_GETITEMTEXT`, or MSAA. The provider therefore fails closed with `PositionSnapshotUnavailable`; it does not use OCR or infer values.

## Live execution consequence

`MT5FilePositionSnapshotProvider` reads the JSON snapshot published by the read-only
`AutoTradePositionReader` indicator. The indicator performs no trade operation, so
its snapshot reflects terminal state independently of the desktop request path.
It is not a service and contains no `OrderSend` or trade request call.

The provider fails closed on a missing, unreadable, truncated, unknown-schema,
incomplete, or stale snapshot. `MT5DesktopAdapter` captures a baseline at the end
of `prepare_order`, and only exactly one new matching position yields `ACCEPTED`.
Every provider failure yields `UNKNOWN`.

Measured on a real demo terminal: a snapshot from an earlier session was refused
as stale rather than read as an empty account, and that snapshot carried the
fields the verifier needs on this broker's build (`ticket`, `symbol`, `type`,
`volume`). The remaining step, observing a snapshot written by the current
indicator on a chart that is attached right now, is a human action recorded in
[demo validation](MT5_DEMO_VALIDATION.md).

A future independent observation method must be explicit, read-only, and approved by the operator. It must not be implemented as an order-placing program.

## Status meanings

- `REQUESTED`: execution was requested or an attempt was recorded.
- `ACCEPTED`: a matching new position was independently observed.
- `REJECTED`: the broker or adapter explicitly rejected the request.
- `UNKNOWN`: the application cannot prove the outcome.
- `DRY_RUN`: no final execution control was used.
