# Verification

Verification is independent of the UI action that initiated an order. A button click is recorded as an action only.

## Current implementation

`PositionChangeVerifier` compares before/after `PositionSnapshot` tuples. It accepts only exactly one new position matching the requested symbol, side, and volume. No match or multiple matches are treated as unverified. The logic is covered by mocked tests.

`MT5PositionSnapshotProvider` reads the Trade table identified by Automation ID `10328`. On the current terminal build, the table exposes headers and a row count but not row text values through UI Automation, Win32 `LVM_GETITEMTEXT`, or MSAA. The provider therefore fails closed with `PositionSnapshotUnavailable`; it does not use OCR or infer values. It is retained for reference and is no longer the default.

## Implemented observation path

`MT5FilePositionSnapshotProvider` reads the JSON snapshot published by the read-only
MT5 Service `AutoTradePositionObserver`. This is the approved independent observation
path: the service performs no trade operation, so the snapshot reflects terminal state
rather than the outcome of the request that is being verified.

It fails closed on a missing, unreadable, truncated, unknown-schema, incomplete, or
stale snapshot. `MT5DesktopAdapter` captures its baseline at the end of `prepare_order`
and records a baseline failure as an error rather than as an empty account. Only exactly
one new matching position yields `ACCEPTED`; every other outcome, including a provider
failure, yields `UNKNOWN`. See [POSITION_OBSERVER.md](POSITION_OBSERVER.md).

## Remaining requirement

A verified result includes the position identifier and the before/after snapshot
reference in the audit record. Live execution stays blocked until that audit linkage and
a controlled demo order have both been exercised end to end.

## Status meanings

- `REQUESTED`: execution was requested or an attempt was recorded.
- `ACCEPTED`: a matching new position was independently observed.
- `REJECTED`: the broker or adapter explicitly rejected the request.
- `UNKNOWN`: the application cannot prove the outcome.
- `DRY_RUN`: no final execution control was used.
