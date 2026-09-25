# Verification

Verification is independent of the UI action that initiated an order. A button click is recorded as an action only.

## Current implementation

`PositionChangeVerifier` compares before/after `PositionSnapshot` tuples. It accepts only exactly one new position matching the requested symbol, side, and volume. No match or multiple matches are treated as unverified. The logic is covered by mocked tests.

`MT5PositionSnapshotProvider` reads the Trade table identified by Automation ID `10328`. On the current terminal build, the table exposes headers and a row count but not row text values. The provider therefore fails closed with `PositionSnapshotUnavailable`; it does not use OCR or infer values.

## Required real provider

Before live execution is enabled, a provider must obtain position snapshots through a separate observation path, such as a non-execution MT5 API or a carefully validated MT5 UI state reader. The provider must capture state before the action and after the action, with bounded timeouts.

A verified result should include the position identifier and the before/after snapshot reference in the audit record. A provider failure must produce `UNKNOWN`, never success.

## Status meanings

- `REQUESTED`: execution was requested or an attempt was recorded.
- `ACCEPTED`: a matching new position was independently observed.
- `REJECTED`: the broker or adapter explicitly rejected the request.
- `UNKNOWN`: the application cannot prove the outcome.
- `DRY_RUN`: no final execution control was used.
