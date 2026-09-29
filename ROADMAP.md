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
       independent observation. Confirmed live on 2026-09-28 (`CLOSED`) and again on
       2026-09-29 on build 6230, where `execute` then `close-position` on the same
       ticket returned `ACCEPTED` then `CLOSED` with no manual step in between.
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
- [x] Add authenticated local APIs.
  - `python -m auto_trade api` serves a loopback-only, token-authenticated,
    read-only API for programs, with a `LocalApiClient` so a caller does not
    re-implement the rules. Every route requires the token, reads included, and
    the query-string form is refused because a URL reaches proxy logs. It has
    no endpoint that places, modifies, or closes an order: the only mutating
    routes are the durable stop and its reset. See [local API](docs/API.md).

## Phase 8 — Testing

- [x] Unit tests for parsing, risk, state, idempotency, and provider behavior.
- [x] Provider-to-workflow integration test.
- [x] Add controlled UI tests.
- [x] Perform demo connection, window, symbol, and dry-run checks.
- [x] Provide a read-only MQL5 indicator position observation method.
- [x] Observe a demo position and confirm verification accepts it.
  - Accepted on 2026-09-28 with evidence on Alpari MT5 6184; the position the
      guarded path created was observed independently. Re-observed on 2026-09-29
      on build 6230, where a position opened *and closed* by hand was seen
      appearing and disappearing. See
      [demo validation](docs/MT5_DEMO_VALIDATION.md), rows 5, 6, 6a, 9 to 13.
- [x] Perform actual demo order only after explicit verification criteria pass.
  - The first attempt found three defects after the click, all fixed; the second
      returned `ACCEPTED` with `order_reference` and evidence. On build 6230 a
      later attempt was rejected by the broker and correctly reported `UNKNOWN`,
      and a following attempt returned `ACCEPTED`; then `close-position` on the
      same ticket returned `CLOSED`.
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
  - The staleness guard now covers both halves. A stale snapshot is refused, and
      an adapter that captured its baseline during the outage recovers by reading
      the account again rather than staying unusable. The account is observed once
      while the order is prepared and once more immediately before the final
      control, and the click is refused unless the two readings are identical. That
      also closes the case that is not an outage at all: a position opened between
      the two readings, by hand or by a terminal recovering a crashed order, can no
      longer be attributed to this order or used to hide one. See
      [recovery](docs/RECOVERY.md).
  - Still open: the same sequence against a real terminal restart, which needs
      a person to kill the terminal mid-order.
- [ ] Structured metrics and latency observability.
  - Done: counters and per-phase latency are derived from the audit log rather
      than collected in memory, so a crashed run is still measured. Exposed as
      `metrics`, `GET /api/metrics`, and the bundle's `metrics.json`. An
      unmeasured phase reports `null`, never zero. See [metrics](docs/METRICS.md).
  - Still open: no alert or threshold, deliberately. A latency figure must never
      be able to look like a verdict on an outcome.
- [x] Security review and dependency review.
  - Two exploitable findings, both fixed with regression tests: a signal `id` was
      used unvalidated as a file name, so any signal source could write outside the
      signal directory; and a `.env` found in the working directory pre-empted the
      reviewed one and could enable live execution. A third finding, an unhandled
      exception from a slow process query, was found by the suite failing under
      load. Three lower-severity items were reviewed and deliberately accepted with
      the reasoning recorded. See [security review](docs/SECURITY_REVIEW.md).
- [ ] Reliability testing across DPI, monitors, focus loss, and dialogs.
  - Measured 2026-09-29 on build 5430: single monitor, `VirtualScreen 1536x864`, no
      DPI scaling fault. DPI was never the obstacle here; what actually needed
      measuring was which controls the build presents. See
      [MT5 demo validation](docs/MT5_DEMO_VALIDATION.md).
- [ ] Decide how build 5430's order dialog is to be traded, or stop supporting it.
  - Build 5430 has no execution-mode *button*. Its `Type` combo (`10338`) already
      reads `Market Execution` when the dialog opens, so the guarded order path
      refuses at `select_market_execution` and this build cannot be traded through
      the guarded path at all.
  - This project will not substitute the combo on its own: a control found once is
      not a control whose behaviour has been established, and treating a default
      as a guarantee is a decision about trading. It needs an operator's decision
      and, if made, a measured identifier and a real-terminal row.
  - Builds 6184 and 6230 both present the button and are unaffected.
- [x] Complete bilingual documentation synchronization.
  - The pages that describe a refusal, a recovery, or an observation now have a
      Persian translation under `docs/fa/`, each linking to the other, and both
      READMEs index both languages: `DASHBOARD.md`, `EXECUTION.md`,
      `METRICS.md`, `POSITION_READER.md`, `RECOVERY.md`, `SAFETY.md`,
      `SIGNAL_PROTOCOL.md`, and `TRACEABILITY.md`.
  - `tests/unit/test_documentation.py` fails when a pair drifts: a missing page,
      a missing cross-link, a dropped safety section, a mistyped identifier, or a
      gate added on one side of the execution tables only. It found three pages
      with no way back to their translation.
  - Eight pages are still English-only and are named in that test, so the gap is
      a decision rather than an oversight: `ARCHITECTURE.md`,
      `ARCHITECTURE_ASSESSMENT.md`, `CONFIGURATION.md`, `COMPLIANCE.md`,
      `TESTING.md`, `VERIFICATION.md`, `STATUS.md`, `PACKAGING.md`,
      `MT5_INTEGRATION.md`, and `MT5_DEMO_VALIDATION.md`.
- [x] Independent review of the hand-written WebSocket client, or replace it with a
      reviewed dependency once the project accepts a runtime dependency.
  - Reviewed on 2026-09-29, and kept: a dependency would be a larger change than
      the three defects it turned out to be hiding. Three findings, all fixed with
      regression tests that fail against the previous code: a JSON number could
      authenticate by rendering to the token's text, the loopback check ran only in
      `start()` and not when the socket was opened, and a closed session left the
      socket open and surfaced a bare `TimeoutError`. The framing rules, the size
      limits, and the handshake were re-confirmed rather than taken on trust. See
      [security review](docs/SECURITY_REVIEW.md).
