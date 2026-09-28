# Project Status

One page for whoever opens this repository, human or otherwise: what is built,
what was actually run and observed, what is refused on purpose, and what is
still open with the reason it is open.

Read this first, then [ROADMAP.md](../ROADMAP.md) for the phase plan and
[demo validation](MT5_DEMO_VALIDATION.md) for the measured MT5 record.

**State as of 2026-09-28.** `main` is green: 324 tests, `ruff` clean, `mypy
--strict` clean. Every claim below was either executed on this machine or is
labelled as not run.

## What this is

A safety-first Windows bridge that takes a signal, decides whether it may be
acted on, and if it may, uses the MT5 desktop UI to place exactly one guarded
order. The two design commitments that shape everything else:

1. **A signal, a decision, a click, a broker acceptance, and an observed
   position are five different events.** The code never collapses them.
2. **A click proves nothing.** Success is only ever established by an
   independent observation, and a click that cannot be corroborated is reported
   as `UNKNOWN` rather than as a trade.

## Verified on a real terminal

Measured on Alpari MT5 build 6184, demo account, per-user install. Details and
the full record table are in [demo validation](MT5_DEMO_VALIDATION.md).

| Capability | Result | How it was established |
| --- | --- | --- |
| Terminal discovery by executable path and instance name | PASS | `diagnostics` reports `found` |
| Read-only position indicator | PASS | compiles 0 errors/0 warnings, registered in the Navigator, writes a complete snapshot every second |
| Snapshot read | PASS | `position-snapshot` reports `AVAILABLE`; a fresh snapshot of an empty account and a 23-hour-old one are told apart |
| Staleness guard | PASS | an old snapshot is refused as `stale`, never read as an empty account |
| Controlled dry-run, BUY and SELL | PASS | reached `ORDER_READY`, closed the dialog, no final control, no position afterwards |
| Guarded order | PASS | `execute --confirm-demo` returned `ACCEPTED` with `order_reference` and evidence |
| Guarded position close | PASS | `close-position --confirm-demo` returned `CLOSED`, ticket gone from the observation |
| Dashboard, diagnostics bundle, configuration wizard | PASS | served and exported from a frozen Windows build |

Both order directions were exercised on the same build that ships the code here.
The order path was exercised twice: the first attempt filled and was reported
`UNKNOWN`, which found three defects; the second returned `ACCEPTED`.

## What is deliberately refused

These are decisions, not gaps. Each one is a place where guessing could cost
money.

| Refused | Why |
| --- | --- |
| The final control without `AUTO_TRADE_ENABLE_EXECUTION=true` | the only code that places an order has no default-on path |
| Closing a position without `AUTO_TRADE_ENABLE_CLOSE=true` | closing is a separate opt-in; allowing an order never allows a close |
| A position this application did not open | the close path requires the ticket in the execution ledger, so a human's position is never touched |
| A close when more than one position is open | the Trade grid exposes row rectangles but no row text, so a ticket cannot be tied to a row without a guess |
| `Close by`, `Close 50%`, `Close All`, `Modify or Delete` | neighbours of the one menu entry this code uses; each would need its own identifiers and its own verification |
| `wss://` and any non-loopback signal endpoint | TLS is not implemented here, and a network source is not approximated |
| Two configured signal sources at once | an operator who set two has not decided which is authoritative |
| A snapshot that is missing, stale, incomplete, or unreadable | reported as unavailable; never as an empty account |
| Hedge, partial close, modify | not implemented; see ROADMAP |
| Any live or funded account | out of scope at every step of this project |

## Architecture in one diagram's worth of words

```text
signal source (file | MQL5 bridge | HTTP | pipe | WebSocket)
      -> normalization into a TradeSignal
      -> risk engine (whitelist, volume, expiration, duplicates, rate)
      -> execution state machine (durable ledger, audit log)
      -> MT5 desktop adapter (semantic controls, no coordinates for orders)
      -> independent observation (read-only MQL5 indicator snapshot)
      -> ACCEPTED / CLOSED, or UNKNOWN
```

Layer rules the code keeps: `domain` holds typed models, enums, exceptions and
protocols only; `application` holds the risk engine, the state machine, the
ledger, the diagnostics bundle and the configuration wizard; `infrastructure`
holds providers, configuration, the Windows adapter and logging; `interfaces`
and `cli` call the same application services. The application layer imports no
infrastructure.

## Local state that is not in this repository

- `.env` is ignored and machine-specific. `python -m auto_trade configure` writes
  it; it always writes `AUTO_TRADE_ENABLE_EXECUTION=false`.
- `logs/`, `signals/` and `dist/` are ignored runtime artifacts.
- The local configuration points at a per-user MT5 install under
  `AppData\Roaming`, not a `Program Files` path.

## Open work, and what blocks each item

| Item | Blocked by |
| --- | --- |
| Recovery after terminal restart | partly done: an order attempt survives a restart through the ledger, and the reader refuses to guess after a terminal restart, but no test covers a crash between the click and the observation |
| Structured metrics and latency observability | nothing; the audit log is structured JSONL but has no counters and no timing summary |
| Authenticated local APIs | nothing; the dashboard is loopback-only with a control token, and the HTTP signal source is a client, not an API |
| Reliability across DPI, monitors, focus loss, dialogs | needs a second machine, or an MT5 build on this one that can be resized and moved; the focus-loss defect found on 2026-09-28 is now covered by the window manager bringing the terminal forward |
| Independent review of the hand-written WebSocket client | needs a second pair of eyes, or a decision to accept a runtime dependency |
| Complete bilingual documentation synchronization | needs a translation pass; the Persian README covers the current state but not every new page |
| Hedge, partial close, modify | needs measured control identifiers and verification of the resulting state |

Settling an execution record an operator later proved is no longer open: see
[recovery](RECOVERY.md). Hedge, partial close, and modify are deliberately not
planned in this phase.

## How to reproduce the verification

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,windows]"
.\scripts\test.ps1
```

On a machine with the demo terminal running, the indicator attached to a chart,
and the flags in the process environment only:

```powershell
$env:AUTO_TRADE_ENABLE_EXECUTION = "true"
$env:AUTO_TRADE_ENABLE_CLOSE = "true"
$env:AUTO_TRADE_DRY_RUN = "false"
python -m auto_trade diagnostics
python -m auto_trade position-snapshot
python -m auto_trade dry-run <signal-file>
python -m auto_trade execute --confirm-demo <signal-file>
python -m auto_trade close-position <ticket> --confirm-demo
python -m auto_trade diagnostics-bundle
```

## Reading order for a new reader

1. This page, for where the project stands.
2. [README.md](../README.md), for what it is and how to run it.
3. [demo validation](MT5_DEMO_VALIDATION.md), for the measured MT5 record and
   the manual steps that remain.
4. [execution](EXECUTION.md), for the two controls that change an account and
   every gate in front of them.
5. [signal protocol](SIGNAL_PROTOCOL.md), for the five signal sources and their
   refusals.
6. [ROADMAP.md](../ROADMAP.md), for the phase plan and the open items.
