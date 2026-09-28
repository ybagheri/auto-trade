[🇮🇷 مستندات فارسی](README.fa.md)

# Auto Trade

A safety-first Windows desktop execution bridge for MetaTrader 5. The project separates signal generation from desktop execution and provides a guarded, fail-closed UI execution path.

> **Important safety and compliance notice**
>
> Automated trading, desktop automation, external trade execution, and connected signal sources may be restricted by a broker, prop firm, account provider, or applicable terms. Users are responsible for confirming that their intended use is permitted. This project does not claim that using the MT5 desktop interface makes an order “manual,” and it does not make claims about any provider’s policy.

[🇬🇧 English Documentation](README.md)

## Features

- Typed Python domain models for signals, requests, results, terminal profiles, risk limits, and audit events.
- Provider protocol with local file, MT5 bridge, and authenticated localhost HTTP, named-pipe, and WebSocket sources.
- Independent risk engine with symbol whitelist, volume, expiration, rate, connection, and position limits.
- Kill switch, demo-only policy, dry-run workflow, duplicate signal protection, and explicit unknown execution state.
- Execution state machine with logged transitions.
- Windows MT5 process discovery using configured executable path and data directory.
- Semantic UIA order-dialog preparation with bounded readiness checks and no coordinate-based order controls.
- Position-change verification abstraction with a fail-closed read-only indicator snapshot provider and durable JSON execution ledger for restart-safe idempotency.
- Rotating JSONL audit logging.
- Local read-only status dashboard with a durable, token-guarded emergency stop.
- CLI diagnostics, a zipped diagnostics bundle, a configuration wizard, and
  non-executing dry-run processing.
- Mocked unit and integration tests that do not require MT5.
- A Windows executable and an installer definition, see [packaging](docs/PACKAGING.md).

## Architecture

```mermaid
flowchart LR
    Signal[Signal Source] --> Bridge[Signal Normalization]
    Bridge --> Risk[Validation and Risk]
    Risk --> Engine[Execution State Machine]
    Engine --> Adapter[MT5 Desktop Adapter]
    Adapter --> MT5[MT5 Desktop]
    MT5 --> Verify[Independent Verification]
    Verify --> Audit[Audit Log]
```

The MT5 desktop adapter can inspect the configured demo process/window and validate the active chart symbol, but final execution controls are intentionally blocked. `--mock` remains available for CI without MT5.

## How It Works

1. A provider receives one explicit signal.
2. The signal is parsed and normalized into `TradeSignal`.
3. The risk engine rejects invalid, expired, duplicate, disallowed, excessive, or rate-limited requests.
4. The workflow records state transitions and prepares the terminal adapter.
5. Dry-run mode stops before any final execution control.
6. A future live adapter must independently verify broker acceptance or a resulting position before reporting success.

A signal, decision, UI click, broker acceptance, and verified position are different events.

## Supported Signal Sources

Implemented: local JSON files, MT5 bridge files written by an MQL5 program, and
three authenticated local sources: an HTTP pull, a named pipe, and a loopback
WebSocket. Exactly one source is used per run; two at once are refused. See
[signal protocol](docs/SIGNAL_PROTOCOL.md).

No provider opens a network listener, no provider can place an order, and
`wss` is refused rather than approximated.

## MT5 Integration

The terminal and data directory are machine specific and are configured through
environment variables or a local `.env` file. Copy `.env.example` to `.env` and
point `AUTO_TRADE_TERMINAL_PATH`, `AUTO_TRADE_DATA_PATH` and
`AUTO_TRADE_INSTANCE_NAME` at the demo terminal you intend to use.

`AUTO_TRADE_INSTANCE_NAME` is matched against the window title and fails closed
when it matches nothing, so an ambiguous or unintended terminal is never driven.
Only the specified demo terminal should be used for development testing. See
[MT5 integration](docs/MT5_INTEGRATION.md)
and [safety](docs/SAFETY.md).

## Read-only Position Indicator

The independent observation path is a read-only MQL5 indicator, not a service and not an order sender:

```powershell
.\scripts\install-position-reader.ps1 `
    -DataPath "<MT5 data directory>" `
    -MetaEditor "C:\Program Files\Alpari MT5_2\MetaEditor64.exe"
```

Attach `AutoTradePositionReader` to a chart once. It reads positions and writes a local snapshot; it contains no `OrderSend`, trade request, or custom log. MT5 may still record indicator load/attachment in its own Journal. The attach step is a human action, because MT5's grids and context menus are not exposed to UI Automation; the measured procedure and the validation record are in [demo validation](docs/MT5_DEMO_VALIDATION.md). See [position reader](docs/POSITION_READER.md).

## Installation

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,windows]"
```

## Quick Start

```powershell
$env:AUTO_TRADE_ALLOWED_SYMBOLS = "BITCOIN"
python -m auto_trade diagnostics
python -m auto_trade make-signal --symbol BITCOIN --action BUY --volume 0.01
python -m auto_trade test-signal examples\signals\example.json
python -m auto_trade dry-run --mock examples\signals\example.json
python -m auto_trade dry-run examples\signals\example.json
python -m auto_trade position-snapshot
python -m auto_trade execute --confirm-demo <signal-file>
python -m auto_trade recovery
python -m auto_trade evaluate --symbol BITCOIN
python -m auto_trade fetch-signal
python -m auto_trade diagnostics-bundle
python -m auto_trade dashboard
```

A signal expires at `timestamp + expiration_seconds` unless it carries an explicit
`expiration`, so generate one with `make-signal` rather than editing the example by
hand. `make-signal` also writes the file that the other commands read.

`fetch-signal` needs exactly one source: `AUTO_TRADE_HTTP_SIGNAL_URL`,
`AUTO_TRADE_PIPE_SIGNAL_NAME`, or `AUTO_TRADE_WS_SIGNAL_URL`, each with its
matching token. It performs one authenticated read and writes the returned signal
into the signal directory, where the normal gates still apply.

## Strategy Integration

A market-analysis library plugs in by exposing a strategy: a string `name` and an
`evaluate(context)` method returning a signal or `None`. Copy
`strategies/example_strategy.py`, replace the body, and set
`AUTO_TRADE_STRATEGY=your_module:build`. The library only proposes a trade; it
cannot reach the terminal, the risk engine, or the audit log, and it cannot widen
its own permissions. See [strategy integration](docs/STRATEGY_INTEGRATION.md).

## Execution

The final order control is refused unless `AUTO_TRADE_ENABLE_EXECUTION=true` is
set explicitly. The gate also refuses while dry-run is active, while the kill
switch is engaged, when the demo-only policy is not met, when no observed
baseline exists, and when the prepared dialog no longer matches what the risk
engine approved. A click is recorded as an action only; acceptance is decided by
independent observation. See [execution](docs/EXECUTION.md).

## Dashboard

`python -m auto_trade dashboard` serves a local read-only status page with signal,
execution, risk, position, and log views, plus an emergency stop. It binds
loopback only and refuses any other address, and its mutating endpoints require the
printed control token. It has no endpoint that can place an order. The stop is
written to a file, so it applies to other processes and survives a restart. See
[dashboard](docs/DASHBOARD.md).

## Demo Mode

Demo-only mode is enabled by default. The normal CLI dry-run path connects to and inspects the configured demo terminal, validates the active chart symbol, and stops before any final execution control. Use `--mock` for a terminal-independent dry run. Real demo order execution is blocked until verification passes controlled validation.

## Configuration

Copy `.env.example` to `.env` for local environment variables, or inspect `config/default.yaml`. The runtime currently reads environment variables and uses safe defaults. Never commit credentials.

`python -m auto_trade configure` writes a reviewed `.env` for this machine: it
shows the current value as the default of every question, refuses a terminal or
data path that does not exist, keeps settings it does not manage, and writes
`AUTO_TRADE_ENABLE_EXECUTION=false` because it has no answer that can enable a
final execution control. See [packaging](docs/PACKAGING.md).

## Diagnostics Bundle

`python -m auto_trade diagnostics-bundle` writes one zip file with the
environment (including the DPI and monitor facts UI automation depends on), the
configuration, terminal discovery, position observation, execution ledger,
pending signals, kill-switch state, and an audit tail. It is read-only, and a
discovery failure is recorded rather than raised. The bundle contains no
credentials: `.env` is excluded, the HTTP token is reported only as configured or
not, and the endpoint URL is stripped of credentials, query, and fragment. See
[packaging](docs/PACKAGING.md).

## Example Signal

```json
{
  "id": "signal-123456",
  "timestamp": "2026-09-25T10:30:00Z",
  "source": "price_action_indicator",
  "symbol": "EURUSD",
  "action": "BUY",
  "volume": 0.10,
  "comment": "PA reversal",
  "strategy": "price_action",
  "metadata": {}
}
```

The complete schema is in [SIGNAL_PROTOCOL.md](docs/SIGNAL_PROTOCOL.md).

## Development

```powershell
.\scripts\test.ps1
```

That runs `pytest`, `ruff`, and `mypy src tests`, and stops on the first failure.
To run them individually, put `typestubs` on `MYPYPATH` first:

```powershell
$env:MYPYPATH = ".\typestubs"
python -m pytest -q
python -m ruff check .
python -m mypy src tests
```

`typestubs/numpy` exists only to shadow numpy's bundled stubs, which require
Python 3.12 syntax while this project type-checks at 3.11. numpy is never
imported here; without the shadow, `mypy` fails on any machine that happens to
have numpy installed for unrelated reasons.

## Testing

Current automated status:

- **PASS — mocked:** 271 unit and integration tests executed.
- **PASS — environment:** Alpari MT5 build 6184 at a per-user path, its data directory, and the running `Alpari-MT5-Demo` process were found and identified by the project's own discovery.
- **PASS — indicator build:** `AutoTradePositionReader` compiles with 0 errors and 0 warnings, is registered under Navigator → Indicators, and is attached to the `EURUSD,M5` chart.
- **PASS — position snapshot:** `position-snapshot` reports `AVAILABLE` from a live, complete, advancing snapshot, and the account it describes has no open position.
- **PASS — staleness guard:** a real snapshot from an earlier session is refused as `stale`, not read as an empty account.
- **PASS — controlled dry-run:** real-terminal BUY and SELL dry-runs on this build reached `ORDER_READY` and closed without a final control, with no position afterwards.
- **AWAITING MANUAL STEP — position verification:** the snapshot path is confirmed, but no position has been opened by hand yet, so the verifier has not accepted a real position. One click in the Trade tab, then read the snapshot. See [demo validation](docs/MT5_DEMO_VALIDATION.md).
- **NOT RUN — real execution:** no real BUY/SELL click or broker order was attempted.
- **MANUAL TEST REQUIRED:** actual symbol switching, DPI behavior, and broker rejection handling.
- **PASS — dashboard:** loopback-only server with token-guarded mutations and a durable emergency stop.
- **PASS — executable:** the Windows build runs `diagnostics`, `diagnostics-bundle`, `dry-run --mock`, and the dashboard; built with Python 3.13 here, so rebuild on the 3.12 baseline.
- **NOT RUN — installer:** the Inno Setup definition was never compiled, because Inno Setup is not installed here.

## Documentation

- [Architecture assessment](docs/ARCHITECTURE_ASSESSMENT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Signal protocol](docs/SIGNAL_PROTOCOL.md)
- [MT5 integration](docs/MT5_INTEGRATION.md)
- [Safety](docs/SAFETY.md)
- [Compliance](docs/COMPLIANCE.md)
- [Testing](docs/TESTING.md)
- [Verification](docs/VERIFICATION.md)
- [Position reader](docs/POSITION_READER.md)
- [Dashboard](docs/DASHBOARD.md)
- [Strategy integration](docs/STRATEGY_INTEGRATION.md)
- [Execution](docs/EXECUTION.md)
- [Traceability inventory](docs/TRACEABILITY.md) · [فارسی](docs/fa/TRACEABILITY.md)
- [Recovery](docs/RECOVERY.md)
- [MT5 demo validation](docs/MT5_DEMO_VALIDATION.md)
- [Packaging](docs/PACKAGING.md)
- [Persian documentation](README.fa.md)

## Roadmap

See [ROADMAP.md](ROADMAP.md). The next milestones are confirming the read-only indicator snapshot on a real demo terminal, observing a demo position opened by hand, and only then a guarded live execution path.

## Contributing

Keep changes testable and safety-focused. Run the full test, lint, and type-check commands before proposing changes. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is provided under the terms in [LICENSE](LICENSE).
