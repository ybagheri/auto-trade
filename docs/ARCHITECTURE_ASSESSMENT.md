# Architecture Assessment

**Assessment date:** 2026-09-25  
**Repository:** `git@github.com:ybagheri/auto-trade.git`  
**Local path:** `D:\Projects\auto-trade`

## Executive Summary

The local repository has no implementation to preserve or refactor. It contains only a `.git` directory, has no commits, and the configured remote returned no branches during inspection. The project therefore starts as a greenfield implementation rather than a migration.

The first implementation should establish a small, testable vertical slice: typed signal and execution domain models, explicit safety gates, a local file signal provider, a terminal discovery interface, a dry-run execution workflow, structured audit records, and a CLI. Real MT5 UI execution must remain disabled until the terminal instance and UI controls have been inspected in a controlled demo session and verification is implemented.

## Existing Repository Findings

- No source files, tests, README, documentation, configuration, packaging metadata, or scripts are present.
- Git branch: `main`.
- Git history: no commits.
- Working tree: clean and empty apart from `.git`.
- Remote: `origin` points to the requested SSH repository, but no remote branches were returned.
- There is no existing architecture, test command, lint command, type-check command, or dependency lockfile to preserve.

## Development Environment Findings

- OS: Windows 10 Home Single Language, version reported as `10.0.26200`, 64-bit.
- Python: 3.12.9 at `C:\Users\BazikadeStore\AppData\Local\Programs\Python\Python312\python.exe`.
- Installed relevant packages include `pywin32` and `comtypes`; `pywinauto`, `pytest`, `ruff`, and `mypy` are not currently available as command-line tools or Python modules.
- Display: one logical screen, bounds `1536x864`; physical adapter reporting includes `1920x1080`.
- DPI: registry `AppliedDPI` is 120; `GetDpiForSystem()` reports 96. This inconsistency must be treated as a diagnostic concern and resolved during UI validation.
- Monitor count: one screen reported by the current Windows Forms query.

## MT5 Findings

- Executable exists: `C:\Program Files\Alpari MT5_2\terminal64.exe`.
- File/product version: `5.0.0.6182`.
- Data directory exists: `C:\Users\BazikadeStore\AppData\Roaming\MetaQuotes\Terminal\AF19ECCF568F855DF9D3196BBF8BF315`.
- A `terminal64.exe` process was detected for the requested executable path.
- The process was responsive and had a visible main window.
- The observed title included `Alpari-MT5-Demo`, `Demo Account`, and the active `XAUUSD,M5` chart.
- No process identity, UI control tree, modal-dialog behavior, symbol lookup behavior, or order verification mechanism has yet been proven.
- The data directory contains existing MT5 profiles, configuration, logs, and MQL5 experts. These are user/terminal data and must not be copied into the application repository or modified as part of the initial implementation.

## What Is Good

- The requested repository and remote are already configured locally.
- A real MT5 installation and data directory are available for controlled demo validation.
- The environment has Python 3.12 and Windows automation building blocks (`pywin32` and `comtypes`).
- The target terminal is running and identifies itself as a demo account in its visible window title.

## Problems and Risks

- There is no safety boundary, audit trail, duplicate protection, or recovery behavior yet.
- UI automation can be broken by focus changes, modal dialogs, terminal restarts, localization, layout changes, DPI differences, and broker behavior.
- A Buy/Sell click is not proof that an order was accepted or that a position exists.
- The currently observed process could be one of several MT5 instances in other environments; executable path alone is insufficient as a long-term identity guarantee.
- The process title and UI text are not a secure account-type proof. Demo-only protection must fail closed unless the configured terminal and account checks are satisfied.
- Network-based execution APIs would create serious security exposure and are not appropriate for the first milestone.
- No test or quality-tooling baseline exists.

## Target Architecture

Use a modular Python package with explicit boundaries:

```text
Signal Provider
      |
Signal Normalization
      |
Risk and Safety Validation
      |
Execution State Machine
      |
Trading Terminal Adapter
      |
MT5 Desktop Automation
      |
Post-action Verification
      |
Structured Audit Log
```

The domain layer will contain immutable, typed models and protocols only. Infrastructure and adapters will implement signal ingestion, persistence, terminal discovery, Windows UI automation, configuration, and logging. Application services will orchestrate the workflow through a state machine. UI and CLI layers will invoke the same application services.

## Retain, Refactor, Remove, Add

### Retain

- The requested repository location and remote.
- The existing MT5 terminal and data directory as external test fixtures only.
- Python 3.12 as the development baseline.

### Refactor

- Not applicable yet; there is no existing code to refactor.

### Remove

- No project files are present to remove. The implementation must not import unrelated user files from the MT5 data directory.

### Add

- Packaging and dependency metadata.
- Domain models, enums, errors, and state machine.
- Signal provider protocol and local file provider.
- Risk limits, kill switch, dry-run, duplicate protection, and expiration checks.
- Terminal profile and discovery abstractions.
- Dry-run terminal adapter with an explicitly unavailable real UI adapter until validated.
- Audit event model and rotating structured logs.
- Diagnostics and CLI commands.
- Unit and integration tests with fakes that do not require MT5.
- English and Persian documentation, safety guidance, signal protocol, and roadmap.

## Initial Implementation Scope

Phase 0/1 should implement the safety and observability foundation before any final execution control is touched:

1. Domain models and protocol definitions.
2. Strict signal parsing and validation.
3. Risk engine with whitelist, volume, expiration, rate, and duplicate protections.
4. Kill switch and dry-run behavior.
5. State machine with explicit `UNKNOWN_EXECUTION` recovery state.
6. File signal provider using a local directory boundary.
7. Fake terminal adapter and diagnostics for terminal discovery.
8. Structured JSONL audit logging.
9. CLI status, diagnostics, test-signal, and dry-run commands.
10. Unit and integration tests.

Real BUY/SELL UI execution, desktop UI, HTTP/WebSocket providers, and packaging are later phases. This sequencing minimizes the chance of creating accidental orders while the verification design is incomplete.

## Validation and Compliance Position

The application is a general desktop automation and execution bridge. It does not claim that using the desktop interface makes an order “manual,” and it does not claim that any broker, prop firm, or account provider permits or forbids this architecture.

Users are responsible for ensuring that automated trading, desktop automation, external trade execution, and any connected signal source are permitted by their broker, prop firm, account provider, and applicable terms.

The application must fail closed on ambiguity. A final UI click is not success; success requires an independent verification method. Initial automated MT5 tests must use only the specified demo terminal and must first cover connection, window detection, symbol detection, dry-run BUY, and dry-run SELL.

## Environment Limitations at Assessment Time

- Existing tests: **NOT RUN — no tests or test runner are installed.**
- Existing application: **NOT RUN — no application exists.**
- MT5 real trading test: **NOT RUN — verification and safety workflow are not implemented.**
- MT5 connection/window inspection: **PARTIAL — executable, data directory, process, responsiveness, and visible demo title were observed.**
- UI control tree, DPI behavior, symbol controls, and order dialogs: **MANUAL VALIDATION REQUIRED.**

## Next Action

Create the minimal project foundation and Phase 0/1 implementation described above, then run mocked tests and quality checks before enabling any demo UI execution capability.
