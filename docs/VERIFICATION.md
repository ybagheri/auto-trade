# Verification

Verification is independent of the UI action that initiated an order. A button click is recorded as an action only.

## Current implementation

`PositionChangeVerifier` compares before/after `PositionSnapshot` tuples. It accepts only exactly one new position matching the requested symbol, side, and volume. No match or multiple matches are treated as unverified. The logic is covered by mocked tests.

`MT5PositionSnapshotProvider` reads the Trade table identified by Automation ID `10328`. On the current terminal build, the table exposes headers and a row count but not row text values through UI Automation, Win32 `LVM_GETITEMTEXT`, or MSAA. The provider therefore fails closed with `PositionSnapshotUnavailable`; it does not use OCR or infer values.

## Live execution consequence

The UI-only build has no independent position observation method. `MT5DesktopAdapter` refuses a final control when it cannot capture a baseline, and verification returns `UNKNOWN` when the post-action state cannot be read. The project does not use an MQL5 program or `OrderSend`, but it also does not claim broker acceptance without evidence.

A future independent observation method must be explicit, read-only, and approved by the operator. It must not be implemented as an order-placing program.

## Status meanings

- `REQUESTED`: execution was requested or an attempt was recorded.
- `ACCEPTED`: a matching new position was independently observed.
- `REJECTED`: the broker or adapter explicitly rejected the request.
- `UNKNOWN`: the application cannot prove the outcome.
- `DRY_RUN`: no final execution control was used.
