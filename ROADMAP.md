# Roadmap

**State as of 2026-09-28:** phases 0 to 9 are complete apart from the items
marked below, phase 10 is open, and every unchecked item in this file is
explained in [project status](docs/STATUS.md) with what blocks it. The two
controls that change an account were each exercised on a real Alpari MT5 demo
terminal and both were accepted: `ACCEPTED` for an order, `CLOSED` for a
position. Read [demo validation](docs/MT5_DEMO_VALIDATION.md) for the measured
record.

## Phase 0 — Repository and Architecture

- [x] Inspect repository and Git state.
- [x] Create architecture assessment.
- [x] Establish Python 3.12 development baseline.
- [x] Add quality-tool configuration.

## Phase 1 — Domain Core

- [x] Add typed signal, order, result, terminal, policy, risk, and audit models.
- [x] Add enums and explicit exceptions.
- [x] Add execution state machine.
- [x] Add risk engine and dry-run workflow.

## Phase 2 — Signal Infrastructure

- [x] Define provider protocol.
- [x] Implement local JSON file provider.
- [x] Add localhost authenticated HTTP provider.
- [x] Add WebSocket, named-pipe, and MT5 bridge providers.
- [x] Add durable idempotency storage.

## Phase 3 — MT5 Discovery

- [x] Validate executable and data-directory existence.
- [x] Match configured process executable path.
- [x] Match process ID, window title, and data-directory identity.
- [x] Add diagnostics for window controls, DPI, monitors, and permissions.

## Phase 4 — MT5 UI Automation

- [x] Inspect the demo terminal accessibility/UI Automation tree.
- [x] Implement terminal/window manager.
- [x] Implement semantic symbol selection.
- [x] Implement volume and SL/TP preparation.
- [x] Implement guarded BUY/SELL action.
- [x] Reject an execution whose prepared dialog no longer matches the approved request.
- [x] Refuse a final control unless execution is explicitly enabled.
- [x] Validate rejection and timeout classification against controlled MT5 states.

## Phase 5 — Safety and Verification

- [x] Kill switch.
- [x] File-backed kill switch shared across processes and restarts.
- [x] Dry-run mode.
- [x] Symbol whitelist and volume limit.
- [x] Expiration, duplicate, and rate protection.
- [x] Demo-only policy in the workflow.
- [x] Persist signal attempts and unknown execution state across restarts.
- [x] Implement independent position-change verification logic.
- [x] Implement a read-only MQL5 indicator for position observation without `OrderSend`.
- [x] Confirm the indicator snapshot on the demo terminal.
  - Confirmed 2026-09-28 on Alpari MT5 6184: `position-snapshot` reports
      `AVAILABLE` with a complete, advancing snapshot. See
      [demo validation](docs/MT5_DEMO_VALIDATION.md), rows 4, 4a, 4b, 4c.
- [x] Implement a guarded position close, proven by the snapshot.
  - Only a position this application opened is closable, only through the
      `Close Position` row menu entry, and only when the ticket disappears from an
      independent observation. Confirmed live on 2026-09-28 (`CLOSED`).
- [ ] Hedge, partial close, and modify: refused today. Each would need its own
      measured control identifiers and its own verification of the new state.

## Phase 6 — Desktop UI

- [x] Build status dashboard.
- [x] Add signal, execution, risk, and log views.
- [x] Add emergency stop and default-dry-run test controls.

## Phase 7 — External Integration

- [x] Document indicator signal bridge.
- [x] Document EA signal bridge without order execution.
- [x] Add a strategy plugin seam for a market-analysis library.
- [ ] Add authenticated local APIs.

## Phase 8 — Testing

- [x] Unit tests for parsing, risk, state, idempotency, and provider behavior.
- [x] Provider-to-workflow integration test.
- [x] Add controlled UI tests.
- [x] Perform demo connection, window, symbol, and dry-run checks.
- [x] Provide a read-only MQL5 indicator position observation method.
- [x] Observe a demo position and confirm verification accepts it.
  - Accepted on 2026-09-28 with evidence on Alpari MT5 6184; the position the
      guarded path created was observed independently. See
      [demo validation](docs/MT5_DEMO_VALIDATION.md), rows 5, 6, 6a.
- [x] Perform actual demo order only after explicit verification criteria pass.
  - The first attempt found three defects after the click, all fixed; the second
      returned `ACCEPTED` with `order_reference` and evidence.
- [x] Reconcile an execution record an operator later proved, without editing the
      ledger by hand. See [recovery](docs/RECOVERY.md); the `UNKNOWN` record from
      the first order attempt was settled with it.

## Phase 9 — Packaging

- [x] Windows executable and installer.
  - [ ] Compile the installer definition on a machine with Inno Setup 6 (not run here).
  - [ ] Rebuild the executable on the Python 3.12 baseline (built on 3.13 here).
- [x] Configuration wizard.
- [x] Diagnostics bundle export.

The executable was built and smoke tested; the installer definition was not
compiled. See [packaging](docs/PACKAGING.md).

## Phase 10 — Production Hardening

- [ ] Recovery after terminal/application restart.
  - A crash between the click and the observation is now covered: the durable
      record stays `REQUESTED` with no result, a restarted process refuses the
      same signal as a duplicate without touching the terminal, the refused
      retry cannot overwrite the record, and only `reconcile` settles it. A
      proved fill whose result never reached disk is still not recorded as
      `ACCEPTED`. See `tests/integration/test_crash_recovery.py`.
  - Still open: the same sequence against a real terminal restart, which needs
      a person to kill the terminal mid-order.
- [ ] Structured metrics and latency observability.
  - Done: counters and per-phase latency are derived from the audit log rather
      than collected in memory, so a crashed run is still measured. Exposed as
      `metrics`, `GET /api/metrics`, and the bundle's `metrics.json`. An
      unmeasured phase reports `null`, never zero. See [metrics](docs/METRICS.md).
  - Still open: no alert or threshold, deliberately. A latency figure must never
      be able to look like a verdict on an outcome.
- [ ] Security review and dependency review.
- [ ] Reliability testing across DPI, monitors, focus loss, and dialogs.
- [ ] Complete bilingual documentation synchronization.
- [ ] Independent review of the hand-written WebSocket client, or replace it with a
      reviewed dependency once the project accepts a runtime dependency.
