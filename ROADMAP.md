# Roadmap

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
- [ ] Add localhost authenticated HTTP provider.
- [ ] Add WebSocket, named-pipe, and MT5 bridge providers.
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
- [ ] Implement guarded BUY/SELL action.
- [x] Implement rejection and timeout classification.
- [ ] Validate rejection and timeout classification against controlled MT5 states.

## Phase 5 — Safety and Verification

- [x] Kill switch.
- [x] Dry-run mode.
- [x] Symbol whitelist and volume limit.
- [x] Expiration, duplicate, and rate protection.
- [x] Demo-only policy in the workflow.
- [x] Persist signal attempts and unknown execution state across restarts.
- [x] Implement independent position-change verification logic.
- [x] Connect verification logic to a fail-closed MT5 position snapshot provider.
- [ ] Expose reliable position values through UIA or an approved observation API.

## Phase 6 — Desktop UI

- [ ] Build status dashboard.
- [ ] Add signal, execution, risk, and log views.
- [ ] Add emergency stop and default-dry-run test controls.

## Phase 7 — External Integration

- [ ] Document indicator signal bridge.
- [ ] Document EA signal bridge without order execution.
- [ ] Add authenticated local APIs.

## Phase 8 — Testing

- [x] Unit tests for parsing, risk, state, idempotency, and provider behavior.
- [x] Provider-to-workflow integration test.
- [ ] Add controlled UI tests.
- [x] Perform demo connection, window, symbol, and dry-run checks.
- [ ] Perform actual demo order only after explicit verification criteria pass.

## Phase 9 — Packaging

- [ ] Windows executable and installer.
- [ ] Configuration wizard.
- [ ] Diagnostics bundle export.

## Phase 10 — Production Hardening

- [ ] Recovery after terminal/application restart.
- [ ] Structured metrics and latency observability.
- [ ] Security review and dependency review.
- [ ] Reliability testing across DPI, monitors, focus loss, and dialogs.
- [ ] Complete bilingual documentation synchronization.
