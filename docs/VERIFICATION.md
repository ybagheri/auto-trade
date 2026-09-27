# Verification

Verification is independent of the UI action that initiated an order. A button click is recorded as an action only.

## Current implementation

`PositionChangeVerifier` compares before/after `PositionSnapshot` tuples. It accepts only exactly one new position matching the requested symbol, side, and volume. No match or multiple matches are treated as unverified. The logic is covered by mocked tests.

`MT5PositionSnapshotProvider` reads the Trade table identified by Automation ID `10328`. On the current terminal build, the table exposes headers and a row count but not row text values through UI Automation, Win32 `LVM_GETITEMTEXT`, or MSAA. The provider therefore fails closed with `PositionSnapshotUnavailable`; it does not use OCR or infer values. It is retained for reference and is no longer the default.

## Implemented observation path

`MT5FilePositionSnapshotProvider` reads the JSON snapshot published by the read-only
MT5 program `AutoTradePositionObserver`. This is the approved independent observation
path: the program performs no trade operation, so the snapshot reflects terminal state
rather than the outcome of the request that is being verified.

It fails closed on a missing, unreadable, truncated, unknown-schema, incomplete, or
stale snapshot. `MT5DesktopAdapter` captures its baseline at the end of `prepare_order`
and records a baseline failure as an error rather than as an empty account. Only exactly
one new matching position yields `ACCEPTED`; every other outcome, including a provider
failure, yields `UNKNOWN`. See [POSITION_OBSERVER.md](POSITION_OBSERVER.md).

## Traceability

A verified result is only meaningful if it can be traced back to the account state that
was observed. `VerificationEvidence` carries both snapshot references into
`ExecutionResult`, and from there into the audit record and the execution ledger:

```json
"evidence": {
  "baseline": "sequence=147 written_at=2026-09-27T06:37:04+00:00 account=53145727 server=Alpari-MT5-Demo positions=1",
  "observed": "sequence=149 written_at=2026-09-27T06:37:06+00:00 account=53145727 server=Alpari-MT5-Demo positions=1",
  "position_id": "382363348"
}
```

`UNKNOWN` outcomes also record the observed reference, so a failure can be investigated
rather than merely counted. The ledger copy is what makes this survive a restart, which
is what `auto-trade recovery` reads.

## Status meanings

- `REQUESTED`: execution was requested or an attempt was recorded.
- `ACCEPTED`: a matching new position was independently observed.
- `REJECTED`: the broker or adapter explicitly rejected the request.
- `UNKNOWN`: the application cannot prove the outcome.
- `DRY_RUN`: no final execution control was used.
